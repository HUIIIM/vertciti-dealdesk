import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";
import { install, reset } from "./server";

// openapi-fetch 在 createClient 时捕获 globalThis.fetch：替身必须在应用模块加载前装好
install();
beforeEach(() => { reset(); window.location.hash = "#/"; try { localStorage.clear(); sessionStorage.clear(); } catch { /* */ } });
afterEach(() => { document.body.innerHTML = ""; });
if (!URL.createObjectURL) Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => {} });
