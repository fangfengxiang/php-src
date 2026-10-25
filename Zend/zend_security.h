/* PHP 7.0.33 unofficial security backport. See docs/security/repair-map.md. */
#ifndef ZEND_SECURITY_H
#define ZEND_SECURITY_H

/* Fixed at build time: never consult INI or allocate in an OOM path. */
#ifndef PHP70_SECURITY_HARDENED
# define PHP70_SECURITY_HARDENED 1
#endif
#if PHP70_SECURITY_HARDENED != 0 && PHP70_SECURITY_HARDENED != 1
# error PHP70_SECURITY_HARDENED must be zero or one
#endif

static zend_always_inline int php70_security_is_hardened(void)
{
	return PHP70_SECURITY_HARDENED;
}

#endif
