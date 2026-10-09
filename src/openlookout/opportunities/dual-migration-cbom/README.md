# dmcbom：「国密 × 抗量子」双迁移密码资产清单

一条命令，扫出一个源码仓库里所有的密码算法使用点，并给每处标两条轴：

- **是否国密**（SM2/SM3/SM4/SM9/ZUC）：密评、等保的国密改造要求用国密算法。
- **量子影响**：RSA/ECC/DH 会被 Shor 算法破解。**SM2/SM9 也一样，它们同样基于（椭圆曲线/配对上的）离散对数**。

因此，国内系统往往要迁两次：先从 RSA 换成 SM2，再从 SM2 换成新一代抗量子算法（NGCC 征集中）。

输出包括：CycloneDX 1.6 CBOM（附带官方 schema 校验）、中文迁移清单、JSON 明细。只依赖标准库；做 schema 校验时需要 `jsonschema`。

```bash
python3 dmcbom.py <repo> --cbom cbom.json --md 迁移清单.md --validate
python3 tests/test_dmcbom.py          # 单元测试（多语言夹具，逐行精确比对）
python3 eval/run_eval.py              # 在 16 个真实公开仓库上复现实测
```

支持的语言和库：

| 语言 | 库 |
|---|---|
| Python（AST + 别名传播） | gmssl / gmssl-python / snowland-smx / hashlib / pyca / pycryptodome / rsa / ecdsa / pynacl / bcrypt |
| Go | tjfoc/gmsm、emmansun/gmsm 与标准库 crypto/* |
| JS/TS/Vue | sm-crypto / gm-crypt / jsencrypt / crypto-js / node:crypto / WebCrypto / node-forge |
| Java | Hutool SmUtil/SecureUtil、BouncyCastle、JCA 字符串 |
| C | GmSSL 3 / OpenSSL / 铜锁 EVP / mbedtls |
| 配置文件 | TLCP / TLS 1.3 国密套件 |

实测结果见 `eval/RESULTS.md`，人工抽检见 `eval/AUDIT.md`。
