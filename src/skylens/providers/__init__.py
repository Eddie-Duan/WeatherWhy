"""数据源适配层：每个外部源一个模块，全部实现 ``base.Provider``，可切换、可降级。

M0 只落地契约（``base.py``）；各 provider 在 M1–M2 逐个补上。
"""
