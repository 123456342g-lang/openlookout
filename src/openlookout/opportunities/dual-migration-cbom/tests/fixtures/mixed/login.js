import { sm2, sm4 as SM4 } from 'sm-crypto'
const JSEncrypt = require('jsencrypt')
const CryptoJS = require('crypto-js')
const crypto = require('crypto')
// sm2.doEncrypt in a comment must not count
export function enc(pub, pwd) {
  const c1 = sm2.doEncrypt(pwd, pub, 1)          // SM2 @7
  const c2 = SM4.encrypt(pwd, 'k')               // SM4 @8
  const r = new JSEncrypt()                      // RSA @9
  const m = CryptoJS.MD5(pwd).toString()         // MD5 @10
  const h = crypto.createHash('sha256')          // SHA-2 @11
  const e = CryptoJS.enc.Utf8.parse(pwd)         // nothing
  return [c1, c2, r, m, h, e]
}
