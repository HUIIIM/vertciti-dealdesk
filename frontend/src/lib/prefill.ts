// 新建交易时带入的候选值：先暂存在本机，交易页打开后写进草稿并登记来源，然后删除。
export const prefillKey = (id: number): string => `dd_prefill_${id}`;
