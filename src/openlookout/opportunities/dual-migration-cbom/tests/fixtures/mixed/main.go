package main

import (
	"crypto/rsa"
	"crypto/sha256"
	"github.com/tjfoc/gmsm/sm2"
	gsm4 "github.com/emmansun/gmsm/sm4"
)

// sm2.GenerateKey in a comment must not count
func main() {
	k, _ := sm2.GenerateKey(nil)         // SM2 @12
	b, _ := gsm4.NewCipher([]byte("0123456789abcdef")) // SM4 @13
	_ = sha256.Sum256([]byte("x"))       // SHA-2 @14
	var r *rsa.PrivateKey                // RSA @15
	_, _, _ = k, b, r
}
