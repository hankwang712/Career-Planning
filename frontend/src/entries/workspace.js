import "../styles/workspace.css";
import { initLegacyFeatureLoader } from "../workspace/legacy-feature-loader.js";

document.documentElement.dataset.frontendBuild = "vite";
initLegacyFeatureLoader();
