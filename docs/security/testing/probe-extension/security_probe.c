/* Test-only module. Never install this probe in a production PHP instance. */
#ifdef HAVE_CONFIG_H
# include "config.h"
#endif
#include "php.h"
#include <stddef.h>
#include "Zend/zend_multiply.h"

static void security_probe_exit_callback(void)
{
	fprintf(stderr, "C EXIT CALLBACK\n");
}

PHP_FUNCTION(security_probe)
{
	array_init(return_value);
#ifdef PHP70_SECURITY_HARDENED
	add_assoc_long(return_value, "hardened", php70_security_is_hardened());
#endif
	add_assoc_long(return_value, "module_api", ZEND_MODULE_API_NO);
	add_assoc_long(return_value, "sizeof_pointer", sizeof(void *));
	add_assoc_long(return_value, "sizeof_zval", sizeof(zval));
	add_assoc_long(return_value, "sizeof_zend_string", sizeof(zend_string));
	add_assoc_long(return_value, "sizeof_HashTable", sizeof(HashTable));
	add_assoc_long(return_value, "sizeof_php_core_globals", sizeof(php_core_globals));
	add_assoc_long(return_value, "max_input_vars", PG(max_input_vars));
	add_assoc_long(return_value, "memory_limit", PG(memory_limit));
}

PHP_FUNCTION(security_probe_allocation)
{
	char *mode;
	size_t mode_len;
	void *ptr = NULL;

	if (zend_parse_parameters(ZEND_NUM_ARGS(), "s", &mode, &mode_len) == FAILURE) {
		return;
	}
	/* The system-failure path exits before extension unloading. */
	if (strcmp(mode, "system_malloc") == 0) {
		atexit(security_probe_exit_callback);
	}
	if (strcmp(mode, "emalloc") == 0) {
		ptr = emalloc(64 * 1024 * 1024);
	} else if (strcmp(mode, "safe_emalloc") == 0) {
		ptr = safe_emalloc((size_t) -1, 2, 0);
	} else if (strcmp(mode, "estrndup") == 0) {
		ptr = estrndup("x", (size_t) -1);
	} else if (strcmp(mode, "zend_strndup") == 0) {
		ptr = zend_strndup("x", (size_t) -1);
	} else if (strcmp(mode, "system_malloc") == 0) {
		ptr = pemalloc((size_t) -4096, 1);
	} else if (strcmp(mode, "inline_guard") == 0) {
		/* Deliberately demonstrates code embedded in old binary extensions. */
		zend_safe_address_guarded((size_t) -1, 2, 0);
	} else if (strcmp(mode, "huge_rounding") == 0) {
		/* Stay within the final 4 KiB page, allowing room for debug
		 * metadata. -4096 is already page-aligned on x86_64 and tests
		 * mmap failure there instead of the intended rounding guard. */
		ptr = emalloc((size_t) -1024);
	} else if (strcmp(mode, "metadata_overflow") == 0) {
		ptr = emalloc((size_t) -1);
	} else if (strcmp(mode, "hash_capacity") == 0) {
		HashTable ht;
		zend_hash_init(&ht, (uint32_t) -1, NULL, ZVAL_PTR_DTOR, 0);
	} else {
		RETURN_FALSE;
	}
	if (ptr) {
		if (strcmp(mode, "system_malloc") == 0 || strcmp(mode, "zend_strndup") == 0) {
			free(ptr);
		} else {
			efree(ptr);
		}
	}
	RETURN_TRUE;
}

PHP_FUNCTION(security_probe_array)
{
	zval *value;
	HashTable *table;
	struct security_bucket_alignment { char prefix; Bucket bucket; };
	size_t bucket_alignment = offsetof(struct security_bucket_alignment, bucket);

	if (zend_parse_parameters(ZEND_NUM_ARGS(), "a", &value) == FAILURE) {
		return;
	}
	table = Z_ARRVAL_P(value);
	array_init(return_value);
	add_assoc_long(return_value, "nTableSize", table->nTableSize);
	add_assoc_long(return_value, "nTableMask", table->nTableMask);
	add_assoc_long(return_value, "arData_mod_pointer_alignment", (uintptr_t) table->arData % sizeof(void *));
	add_assoc_long(return_value, "Bucket_alignment", bucket_alignment);
	add_assoc_long(return_value, "arData_mod_bucket_alignment", (uintptr_t) table->arData % bucket_alignment);
}

static const zend_function_entry security_probe_functions[] = {
	PHP_FE(security_probe, NULL)
	PHP_FE(security_probe_allocation, NULL)
	PHP_FE(security_probe_array, NULL)
	PHP_FE_END
};

zend_module_entry security_probe_module_entry = {
	STANDARD_MODULE_HEADER,
	"security_probe",
	security_probe_functions,
	NULL, NULL, NULL, NULL, NULL,
	"1.0",
	STANDARD_MODULE_PROPERTIES
};

#ifdef COMPILE_DL_SECURITY_PROBE
ZEND_GET_MODULE(security_probe)
#endif
