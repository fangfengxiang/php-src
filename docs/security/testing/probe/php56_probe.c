/* Test-only PHP 5.6 extension. Build against the exact configured source tree.
 * Never load in a web worker: boundary cases intentionally terminate the CLI.
 * Synthetic concat cases change zval length metadata, not backing storage.
 */
#include "php.h"
#include "php_variables.h"
#include "zend_operators.h"
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char php56_native_marker[4096];

static void php56_probe_atexit(void)
{
	FILE *fp = fopen(php56_native_marker, "wb");
	if (fp != NULL) {
		fputs("native-atexit\n", fp);
		fclose(fp);
	}
}

PHP_FUNCTION(php56_probe_arm_atexit)
{
	char *path;
	int length;
	if (zend_parse_parameters(ZEND_NUM_ARGS() TSRMLS_CC, "s", &path, &length) == FAILURE) {
		return;
	}
	if (length <= 0 || (size_t)length >= sizeof(php56_native_marker)
			|| memchr(path, '\0', length) != NULL) {
		php_error_docref(NULL TSRMLS_CC, E_WARNING, "Invalid native marker path");
		RETURN_FALSE;
	}
	memcpy(php56_native_marker, path, length + 1);
	RETURN_BOOL(atexit(php56_probe_atexit) == 0);
}

PHP_FUNCTION(php56_probe_build_info)
{
	array_init(return_value);
	add_assoc_string(return_value, "php_version", PHP_VERSION, 1);
	add_assoc_long(return_value, "module_api", ZEND_MODULE_API_NO);
	add_assoc_long(return_value, "sizeof_size_t", sizeof(size_t));
	add_assoc_long(return_value, "sizeof_long", sizeof(long));
	add_assoc_long(return_value, "sizeof_zval", sizeof(zval));
	add_assoc_long(return_value, "sizeof_hashtable", sizeof(HashTable));
	add_assoc_bool(return_value, "debug", ZEND_DEBUG);
#ifdef ZTS
	add_assoc_bool(return_value, "zts", 1);
#else
	add_assoc_bool(return_value, "zts", 0);
#endif
}

static void php56_table_snapshot(zval *snapshots, char *name, HashTable *table)
{
	zval *entry;
	MAKE_STD_ZVAL(entry);
	array_init(entry);
	add_assoc_long(entry, "capacity", table->nTableSize);
	add_assoc_long(entry, "mask", table->nTableMask);
	add_assoc_long(entry, "elements", table->nNumOfElements);
	add_assoc_zval(snapshots, name, entry);
}

static zval *php56_array_child(zval *parent, char *key, uint length TSRMLS_DC)
{
	zval **child;
	if (zend_hash_find(Z_ARRVAL_P(parent), key, length + 1, (void **)&child) == FAILURE
			|| Z_TYPE_PP(child) != IS_ARRAY) {
		php_error_docref(NULL TSRMLS_CC, E_ERROR, "Native probe did not find expected input array");
		return NULL;
	}
	return *child;
}

PHP_FUNCTION(php56_probe_input_tables)
{
	zval *root, *snapshots, *nested, *appended, *numeric, *replacement;
	zval ordinary;
	zval **first_append;

	MAKE_STD_ZVAL(root);
	array_init(root);
	MAKE_STD_ZVAL(snapshots);
	array_init(snapshots);
	php56_table_snapshot(snapshots, "root_empty", Z_ARRVAL_P(root));
	INIT_ZVAL(ordinary);
	array_init(&ordinary);
	php56_table_snapshot(snapshots, "ordinary_empty", Z_ARRVAL(ordinary));
	add_assoc_string(&ordinary, "first", "value", 1);
	php56_table_snapshot(snapshots, "ordinary_one", Z_ARRVAL(ordinary));
	zval_dtor(&ordinary);

	/* Exercise the real parser/register API, never edit HashTable metadata. */
	php_register_variable_safe("nested[first]", "one", 3, root TSRMLS_CC);
	nested = php56_array_child(root, "nested", sizeof("nested") - 1 TSRMLS_CC);
	php56_table_snapshot(snapshots, "root_one", Z_ARRVAL_P(root));
	php56_table_snapshot(snapshots, "nested_one", Z_ARRVAL_P(nested));
	php_register_variable_safe("nested[second]", "two", 3, root TSRMLS_CC);
	php56_table_snapshot(snapshots, "nested_two", Z_ARRVAL_P(nested));
	php_register_variable_safe("nested[third]", "three", 5, root TSRMLS_CC);
	php56_table_snapshot(snapshots, "nested_three", Z_ARRVAL_P(nested));
	php_register_variable_safe("nested[first]", "replacement", 11, root TSRMLS_CC);
	php56_table_snapshot(snapshots, "nested_overwrite", Z_ARRVAL_P(nested));

	php_register_variable_safe("append[][leaf]", "value", 5, root TSRMLS_CC);
	appended = php56_array_child(root, "append", sizeof("append") - 1 TSRMLS_CC);
	php56_table_snapshot(snapshots, "append_outer_one", Z_ARRVAL_P(appended));
	if (zend_hash_index_find(Z_ARRVAL_P(appended), 0, (void **)&first_append) == FAILURE
			|| Z_TYPE_PP(first_append) != IS_ARRAY) {
		php_error_docref(NULL TSRMLS_CC, E_ERROR, "Native probe did not find appended array");
		return;
	}
	php56_table_snapshot(snapshots, "append_inner_one", Z_ARRVAL_PP(first_append));

	php_register_variable_safe("numeric[0]", "zero", 4, root TSRMLS_CC);
	php_register_variable_safe("numeric[1]", "one", 3, root TSRMLS_CC);
	php_register_variable_safe("numeric[2]", "two", 3, root TSRMLS_CC);
	numeric = php56_array_child(root, "numeric", sizeof("numeric") - 1 TSRMLS_CC);
	php56_table_snapshot(snapshots, "numeric_three", Z_ARRVAL_P(numeric));
	php_register_variable_safe("replace", "scalar", 6, root TSRMLS_CC);
	php_register_variable_safe("replace[leaf]", "array", 5, root TSRMLS_CC);
	replacement = php56_array_child(root, "replace", sizeof("replace") - 1 TSRMLS_CC);
	php56_table_snapshot(snapshots, "scalar_replaced_by_array", Z_ARRVAL_P(replacement));

	array_init(return_value);
	add_assoc_zval(return_value, "snapshots", snapshots);
	add_assoc_zval(return_value, "registered", root);
}

PHP_FUNCTION(php56_probe_boundary)
{
	char *mode;
	int length;
	void *pointer;
	volatile size_t impossible = (size_t)-1;
	static void * volatile allocation_sink;
	zval left, right, result, character;
	char left_storage[2] = "L", right_storage[2] = "R";

	if (zend_parse_parameters(ZEND_NUM_ARGS() TSRMLS_CC, "s", &mode, &length) == FAILURE) {
		return;
	}
	if (strcmp(mode, "safe_mul_overflow") == 0) {
		pointer = safe_emalloc(impossible, 2, 0);
		efree(pointer);
	} else if (strcmp(mode, "safe_add_overflow") == 0) {
		pointer = safe_emalloc(1, impossible, 1);
		efree(pointer);
	} else if (strcmp(mode, "safe_string_int_max") == 0) {
		pointer = safe_emalloc_string(1, (size_t)INT_MAX, 1);
		efree(pointer);
	} else if (strcmp(mode, "system_malloc_size_max") == 0) {
		/* A real libc malloc failure for an impossible request. This is not
		 * physical RAM exhaustion, a PHP memory_limit, or fault injection. */
		pointer = pemalloc(impossible, 1);
		allocation_sink = pointer;
		free(pointer);
	} else {
		/* Synthetic boundary probes: tiny backing buffers and deliberately
		 * impossible length metadata. Only guard ordering is tested. */
		INIT_ZVAL(left);
		INIT_ZVAL(right);
		INIT_ZVAL(result);
		INIT_ZVAL(character);
		ZVAL_STRINGL(&left, left_storage, INT_MAX, 0);
		ZVAL_STRINGL(&right, right_storage, 1, 0);
		ZVAL_LONG(&character, 'R');
		if (strcmp(mode, "synthetic_concat_separate") == 0) {
			concat_function(&result, &left, &right TSRMLS_CC);
		} else if (strcmp(mode, "synthetic_concat_in_place") == 0) {
			concat_function(&left, &left, &right TSRMLS_CC);
		} else if (strcmp(mode, "synthetic_add_string") == 0) {
			add_string_to_string(&left, &left, &right);
		} else if (strcmp(mode, "synthetic_add_char") == 0) {
			add_char_to_string(&left, &left, &character);
		} else if (strcmp(mode, "synthetic_concat_negative") == 0) {
			Z_STRLEN(left) = -1;
			concat_function(&result, &left, &right TSRMLS_CC);
		} else {
			php_error_docref(NULL TSRMLS_CC, E_WARNING, "Unknown native probe mode");
			RETURN_FALSE;
		}
	}
	php_error_docref(NULL TSRMLS_CC, E_ERROR, "Native boundary call unexpectedly returned");
}

ZEND_BEGIN_ARG_INFO_EX(arginfo_php56_probe_none, 0, 0, 0)
ZEND_END_ARG_INFO()
ZEND_BEGIN_ARG_INFO_EX(arginfo_php56_probe_string, 0, 0, 1)
	ZEND_ARG_INFO(0, value)
ZEND_END_ARG_INFO()

static const zend_function_entry php56_probe_functions[] = {
	PHP_FE(php56_probe_arm_atexit, arginfo_php56_probe_string)
	PHP_FE(php56_probe_build_info, arginfo_php56_probe_none)
	PHP_FE(php56_probe_input_tables, arginfo_php56_probe_none)
	PHP_FE(php56_probe_boundary, arginfo_php56_probe_string)
	PHP_FE_END
};

zend_module_entry php56_probe_module_entry = {
	STANDARD_MODULE_HEADER,
	"php56_probe",
	php56_probe_functions,
	NULL, NULL, NULL, NULL, NULL,
	"1.0",
	STANDARD_MODULE_PROPERTIES
};

ZEND_GET_MODULE(php56_probe)
