import "../styles/workspace.css";
import { initLegacyFeatureLoader } from "../workspace/legacy-feature-loader.ts";

document.documentElement.dataset.frontendBuild = "vite";
if (document.body?.dataset.legacyFeatures !== "eager") initLegacyFeatureLoader();
