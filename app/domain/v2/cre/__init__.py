"""机构级商业地产承销引擎（office / retail / industrial，逐租约、按月）。

对标 Argus Enterprise 的通行口径：逐租约现金流、到期续租概率与市场租赁假设（MLA）加权、空置期、免租、
TI / LC、按租约类型的费用回收（NNN / Gross / 基年）、一般空置抵减已建模的周转空置；债务支持只付息期、
固定 / 浮动（SOFR 曲线 + 利差 + 利率上限）；退出按下一年 NOI；输出无杠杆 / 有杠杆 IRR、权益倍数、NPV、
DSCR、债务收益率，以及按 IRR 门槛的 GP / LP 分配瀑布。

入口：engine.run(inputs) → 结果字典；inputs 结构见 inputs.CreInputs。纯函数、无 I/O、同输入同输出。
"""
