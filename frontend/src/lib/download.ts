// 把下载响应存成文件：文件名取服务端 Content-Disposition（filename* 优先，支持中文），取不到用兜底名。
export function filenameOf(r: Response, fallback: string): string {
  const cd = r.headers.get("content-disposition") ?? "";
  const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  if (star?.[1]) { try { return decodeURIComponent(star[1]); } catch { /* 坏编码：退回普通 filename */ } }
  const plain = /filename="?([^";]+)"?/i.exec(cd);
  return plain?.[1] ?? fallback;
}

export async function saveResponse(r: Response, fallback: string): Promise<string> {
  const name = filenameOf(r, fallback);
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a"); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url);
  return name;
}
