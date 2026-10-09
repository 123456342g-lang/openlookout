# dmcbom 真实仓库实测（自动生成）

运行时间：2026-10-09 12:29（UTC+8）；仓库为浅克隆的默认分支 HEAD。

| 仓库 | commit | 扫描文件 | 发现 | 其中调用点 | 国密发现 | 国密调用点 | 国密且不在 CBOMkit 文档覆盖内 | Schema |
|---|---|---|---|---|---|---|---|---|
| fg193/sgcc | 725b018a1982 | 1 | 2 | 2 | 2 | 2 | 2 | 通过 |
| szgenle/zhmm | 2fcc67b4c399 | 104 | 32 | 20 | 10 | 5 | 10 | 通过 |
| rootklt/gmssl | ba24d5771d5e | 9 | 11 | 4 | 11 | 4 | 11 | 通过 |
| C0de-breaker01/sm2-sm3-sm4-toolkit | d8e749977a43 | 7 | 37 | 25 | 36 | 24 | 36 | 通过 |
| easyops-cn/ntls-go | 658830d86656 | 45 | 207 | 102 | 48 | 24 | 48 | 通过 |
| det101/gmkit | dbd39d6ca451 | 21 | 21 | 11 | 20 | 10 | 20 | 通过 |
| dazhengs/tools | e8bd47dfbcf4 | 30 | 31 | 29 | 8 | 8 | 8 | 通过 |
| langdadong/vue-cryptographic-app | 9c32f510d195 | 41 | 2 | 2 | 0 | 0 | 0 | 通过 |
| wote-book/ai-privacy-exam-grading-system | 87f74441aa70 | 60 | 18 | 18 | 15 | 15 | 15 | 通过 |
| wcnwyx/gm-encryption | 9872421e7ad2 | 12 | 14 | 8 | 13 | 7 | 0 | 通过 |
| ZZMarquis/gmhelper | 3ccaf2215b57 | 34 | 108 | 16 | 44 | 10 | 1 | 通过 |
| yirenyiqi/sm-crypto | 64e344365ac1 | 15 | 3 | 0 | 3 | 0 | 3 | 通过 |
| gotoworld/hsd-cipher-sm | b725f43c4224 | 26 | 31 | 20 | 27 | 16 | 4 | 通过 |
| Hyperledger-TWGC/java-gm | b238e9f3c07f | 31 | 46 | 7 | 41 | 5 | 1 | 通过 |
| pallets/itsdangerous | 672971d66a2e | 18 | 13 | 3 | 0 | 0 | 0 | 通过 |
| psf/requests | 611c6162cbc4 | 45 | 5 | 0 | 0 | 0 | 0 | 通过 |
| **合计** | | 499 | 581 | 267 | 278 | 130 | 159 | |

“不在 CBOMkit 文档覆盖内”= 该发现来自的库不在 sonar-cryptography README 声明的覆盖表里（JCA、BouncyCastle 轻量 API、pyca、Go 标准库）。这是按文档推断，**没有实际运行 SonarQube 对照**。
