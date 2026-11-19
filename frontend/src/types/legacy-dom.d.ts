/**
 * 旧版经典脚本大量把 querySelector/getElementById/event.target 的结果直接当具体元素子类用
 * （.value/.disabled/.dataset/.style/.closest/.key 等）。逐个 cast 噪声大且不改行为，
 * 这里给 legacy 程序（checkJs，渐进收紧）补一层宽松 DOM 成员声明，先让有价值的检查
 * （未定义引用、调用元数、真实类型不匹配、算术运算）跑起来。
 * 模块层（tsconfig.json）不含本文件，仍用 lib.dom 的精确类型；随旧脚本模块化逐步移除本 shim。
 */
export {};

declare global {
  interface Element {
    style: any;
    dataset: any;
    offsetLeft: any;
    offsetTop: any;
    offsetWidth: any;
    offsetHeight: any;
    value: any;
    disabled: any;
    getTotalLength(): any;
    getPointAtLength(distance: any): any;
  }
  interface HTMLElement {
    value: any;
    disabled: any;
    checked: any;
    rows: any;
    max: any;
    min: any;
    files: any;
    getContext(contextId: any, ...args: any[]): any;
    setSelectionRange(start: any, end: any, ...args: any[]): any;
    reportValidity(): any;
    reset(): any;
  }
  interface EventTarget {
    closest(selectors: any): any;
    id: any;
    dataset: any;
    style: any;
    value: any;
    disabled: any;
    classList: any;
  }
  interface Event {
    key: any;
    propertyName: any;
    clientX: any;
    clientY: any;
  }
}
