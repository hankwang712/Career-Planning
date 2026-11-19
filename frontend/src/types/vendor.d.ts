/**
 * 第三方库以 classic script 挂到全局（chart.umd.js、gsap、lenis、fuse、marked、DOMPurify 等）。
 * 这里给出宽松的环境声明，让 checkJs 能识别这些全局；后续按需替换为各库的真实类型。
 */
declare var Chart: any;
declare var gsap: any;
declare var ScrollTrigger: any;
declare var Lenis: any;
declare var Fuse: any;
declare var marked: any;
declare var DOMPurify: any;
