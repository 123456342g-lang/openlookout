package demo;

import cn.hutool.crypto.SmUtil;
import org.bouncycastle.crypto.engines.SM2Engine;
import javax.crypto.Cipher;

public class Gm {
    // SmUtil.sm4() mentioned in comment
    void run() throws Exception {
        SM2Engine e = new SM2Engine();                          // SM2 @10
        byte[] h = SmUtil.sm3("abc").getBytes();                // SM3 @11
        Cipher c = Cipher.getInstance("SM4/CBC/PKCS5Padding");  // SM4 @12
        java.security.Signature s = java.security.Signature.getInstance("SHA256withRSA"); // RSA+SHA-2 @13
    }
}
