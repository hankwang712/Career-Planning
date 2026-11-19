/**
 * 旧版全局脚本（static/app-*.js，共享全局作用域）与 TS 模块层之间的桥接契约。
 * 这些函数由经典脚本挂到 window 上；模块层通过这里的类型安全地调用它们。
 * 随着旧脚本逐步模块化，这里的声明会相应收敛为显式 import。
 */
export {};

declare global {
  interface Window {
    __workspaceLegacyFeatureLoaderReady?: boolean;
    showSection?: (sectionId: string, ...rest: unknown[]) => unknown;
    showToast?: (title: string, message: string, kind?: string, duration?: number) => void;
    openAssessmentModal?: (test?: string) => unknown;
    openDeepTestModal?: (...args: unknown[]) => unknown;
    openDeepTestRunnerPage?: (type: string, restart?: boolean) => unknown;
    openDeepTestResultPage?: (...args: unknown[]) => unknown;
    toggleHistoryPanel?: () => unknown;
    ensureWorkspaceSectionReady?: (sectionId: string) => Promise<void>;
    /** 旧脚本动态挂载的其它全局函数（按名字访问）。 */
    [key: string]: unknown;
  }
}
