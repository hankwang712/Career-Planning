/**
 * 旧版经典脚本通过 window 动态挂载/读取大量函数与命名空间。
 *  legacy 程序（checkJs，渐进收紧）用宽松索引签名兼容这些动态访问；
 *  模块层（tsconfig.json）仍用 globals.d.ts 的严格类型。
 */
export {};

declare global {
  interface Window {
    [key: string]: any;
  }
}
