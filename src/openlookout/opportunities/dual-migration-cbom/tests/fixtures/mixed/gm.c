#include <gmssl/sm2.h>
/* sm2_sign( in a block comment */
int f(SM2_KEY *k, const uint8_t *d, uint8_t *sig, size_t *n) {
    SM3_CTX c; sm3_init(&c);              /* SM3 @4 */
    const EVP_CIPHER *ci = EVP_sm4_cbc(); /* SM4 @5 */
    return sm2_sign(k, d, sig, n);        /* SM2 @6 */
}
