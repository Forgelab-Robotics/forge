# forge-policy

通用 policy 节点协议与 Dora runner。具体算法只需要提供 policy adapter、关节动作构造函数和输入映射，runner 负责处理 `tick`、`proprio_state`、图像缓存、`PolicyCommand` 生命周期命令和可选的 `PolicyCommandStatus` 输出。
