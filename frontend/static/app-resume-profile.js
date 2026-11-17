// 简历档案：上传、解析、分析与删除
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function renderResumeProfileSection(data) {
  const state = data || emptyResumeProfile();
  renderReportResumePanel(state);
  const uploadStatus = document.getElementById("resumeUploadStatus");
  const uploadMeta = document.getElementById("resumeUploadMeta");
  const analyzeStatus = document.getElementById("resumeAnalyzeStatus");
  const analyzeMeta = document.getElementById("resumeAnalyzeMeta");
  const confidence = document.getElementById("resumeConfidence");
  const modelHint = document.getElementById("resumeModelHint");
  const summary = document.getElementById("resumeCandidateSummary");
  const roleTags = document.getElementById("resumeRoleTags");
  const matchedTags = document.getElementById("resumeMatchedKeywordTags");
  const missingTags = document.getElementById("resumeMissingKeywordTags");
  const jobTags = document.getElementById("resumeJobKeywordTags");
  const overviewList = document.getElementById("resumeOverviewList");
  const evidenceList = document.getElementById("resumeEvidenceList");
  const analysisResult = document.getElementById("resumeAnalysisResult");
  const analysisResultMeta = document.getElementById("resumeAnalysisResultMeta");
  const quickBoard = document.getElementById("resumeQuickBoard");
  const jobAssist = document.getElementById("resumeJobAssist");
  const profile = state.profile || null;
  const matcher = state.matcher && typeof state.matcher === "object" ? state.matcher : {};
  const analysisMode = String(matcher.analysis_mode || state.analysis_meta?.analysis_mode || "").trim();
  const recommendedDirections = Array.isArray(matcher.recommended_directions) ? matcher.recommended_directions : [];

  setResumeJobDescription(state.job_description || "");
  syncResumeJobInputFrame();
  if (jobAssist) {
    jobAssist.innerHTML = resumeJobAssistHtml(state.job_description || "", analysisMode, recommendedDirections);
  }

  if (uploadStatus) uploadStatus.textContent = state.file_name ? "已上传" : "未上传";
  if (uploadMeta) {
    uploadMeta.textContent = state.file_name
      ? `${state.file_name} · ${String(state.file_type || "pdf").toUpperCase()} · ${(Number(state.file_size || 0) / 1024).toFixed(1)}KB · ${formatUnixTime(state.uploaded_at)}`
      : "请先上传 PDF 或 DOCX 简历";
  }
  if (analyzeStatus) {
    if (state.status === "analyzed") analyzeStatus.textContent = "已完成";
    else if (state.status === "failed") analyzeStatus.textContent = "失败";
    else if (state.status === "analyzing") analyzeStatus.textContent = "分析中";
    else analyzeStatus.textContent = "待分析";
  }
  if (analyzeMeta) {
    const meta = state.analysis_meta || {};
    if (state.status === "analyzed") {
      const matchedCount = Array.isArray(matcher.matched_keywords) ? matcher.matched_keywords.length : 0;
      const jobCount = Array.isArray(matcher.job_keywords) ? matcher.job_keywords.length : 0;
      analyzeMeta.textContent = analysisMode === "resume_review"
        ? `页数 ${meta.page_count || 0} · 字符 ${meta.char_count || 0} · 简历诊断`
        : `页数 ${meta.page_count || 0} · 字符 ${meta.char_count || 0} · 命中 ${matchedCount}/${jobCount}`;
    } else if (state.status === "analyzing") {
      analyzeMeta.textContent = `${meta.stage_detail || "正在分析中..."}`;
    } else {
      analyzeMeta.textContent = humanizeResumeErrorMessage(state.error_message || meta.stage_detail || "") || "等待简历上传，JD 可选";
    }
  }

  if (confidence) confidence.textContent = resumeScoreLabel(resumeEvidenceScore(profile));
  if (modelHint) {
    const model = String(state.analysis_meta?.model || "").trim();
    modelHint.textContent = profile
      ? `${model || "分析模型"} · ${formatUnixTime(state.analyzed_at)}`
      : (state.status === "failed"
        ? "本次分析失败，可修正文件后重试"
        : "等待首次匹配结果");
  }
  if (summary) summary.textContent = resumeProfileSummaryText(state, profile);

  if (!resumeTaskState.uploadInFlight) {
    hideResumeProgress("upload");
  }
  if (!resumeTaskState.analyzeInFlight) {
    if (state.status === "analyzing") setResumeProgress("analyze", 100, `${state.analysis_meta?.stage_detail || "分析中"}`, true);
    else hideResumeProgress("analyze");
  }

  if (roleTags) {
    const roles = previewTagValues((profile?.roles_detected || []).map((item) => item.role), 6);
    roleTags.innerHTML = careerTagHtml(roles, "等待识别岗位角色", "accent");
  }
  if (matchedTags) {
    matchedTags.innerHTML = analysisMode === "resume_review"
      ? careerTagHtml([], "当前为简历诊断模式", "primary")
      : careerTagHtml(previewTagValues(matcher.matched_keywords || [], 8), "暂无命中关键词", "primary");
  }
  if (missingTags) {
    missingTags.innerHTML = analysisMode === "resume_review"
      ? careerTagHtml([], "未提供 JD，技能要求待核实", "soft")
      : careerTagHtml(previewTagValues(matcher.missing_keywords || [], 8), "已识别技能暂无未体现项，仍需验证熟练度", "soft");
  }
  if (jobTags) {
    jobTags.innerHTML = analysisMode === "resume_review"
      ? careerTagHtml(previewTagValues(recommendedDirections, 6), "未提供 JD，系统已给出建议方向", "accent")
      : careerTagHtml(previewTagValues(matcher.job_keywords || [], 10), "等待解析岗位文本", "accent");
  }
  if (quickBoard) {
    quickBoard.innerHTML = profile
      ? resumeQuickBoardHtml(profile, matcher, analysisMode, recommendedDirections)
      : `<div class="career-list-empty">${escHtml(state.file_name ? (state.status === "failed" ? "这份简历本次没有成功生成摘要，请根据上方提示修正后重新开始匹配。" : "简历已上传，点击“开始匹配”后会在这里显示简明概览卡片。") : "上传并分析后会在这里显示简明概览卡片")}</div>`;
  }

  if (overviewList) {
    overviewList.innerHTML = profile
      ? resumeOverviewCardsHtml(profile, matcher, analysisMode, recommendedDirections)
      : `<div class="career-list-empty">${escHtml(state.status === "failed" ? "本次分析失败，暂时没有结构化概览。" : "等待结构化概览")}</div>`;
  }

  if (analysisResultMeta) {
    const matchedCount = Array.isArray(matcher.matched_keywords) ? matcher.matched_keywords.length : 0;
    const jobCount = Array.isArray(matcher.job_keywords) ? matcher.job_keywords.length : 0;
    analysisResultMeta.textContent = state.analyzed_at
      ? (analysisMode === "resume_review"
        ? `最近生成：${formatUnixTime(state.analyzed_at)} · 简历诊断模式`
        : `最近生成：${formatUnixTime(state.analyzed_at)} · 命中 ${matchedCount}/${jobCount}`)
      : "等待分析";
  }
  if (analysisResult) {
    analysisResult.innerHTML = resumeAnalysisDashboardHtml(state, profile, matcher, analysisMode, recommendedDirections);
    initResumeStackDecks(analysisResult);
  }
  renderResumeReportModal(state, profile, matcher, analysisMode, recommendedDirections);

  if (evidenceList) {
    evidenceList.innerHTML = profile
      ? resumeEvidenceCardsHtml(profile)
      : resumeEvidencePlaceholderHtml();
  }
  syncResumeJudgeFlow(state);
}

async function refreshResumeProfile(force = false) {
  try {
    const data = await loadResumeProfile(force);
    renderResumeProfileSection(data);
    refreshUnifiedExperience();
  } catch (error) {
    showToast("简历状态加载失败", error.message, "error", 2000);
  }
}

function pickResumeFile() {
  const input = document.getElementById("resumeFileInput");
  if (input) input.click();
}

function pickResumePdf() {
  pickResumeFile();
}

async function onResumeFileSelected(event) {
  const file = event?.target?.files?.[0];
  if (!file) return;
  const lowerName = String(file.name || "").toLowerCase();
  if (!lowerName.endsWith(".pdf") && !lowerName.endsWith(".docx")) {
    showToast("仅支持 PDF 或 DOCX", "请上传 .pdf 或 .docx 简历文件", "warning", 2000);
    return;
  }
  if (resumeTaskState.uploadInFlight || resumeTaskState.analyzeInFlight) {
    showToast("请稍候", "当前有任务正在执行中。", "warning", 1800);
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  resumeTaskState.uploadInFlight = true;
  resumeTaskState.forceInputView = true;
  syncResumeJudgeFlow(getResumeProfileFromCache());
  updateResumeActionButtons();
  const uploadStatus = document.getElementById("resumeUploadStatus");
  const uploadMeta = document.getElementById("resumeUploadMeta");
  if (uploadStatus) uploadStatus.textContent = "上传中";
  if (uploadMeta) uploadMeta.textContent = `正在上传：${file.name}`;
  setResumeProgress("upload", 0, "上传中 0%", true);
  try {
    const payload = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", resolveApiUrl("/api/resume/upload"), true);
      xhr.withCredentials = true;
      xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        const percent = Math.min(99, (e.loaded / e.total) * 100);
        setResumeProgress("upload", percent, `上传中 ${Math.round(percent)}%`, true);
      };
      xhr.onload = () => {
        let data = {};
        try {
          data = JSON.parse(xhr.responseText || "{}");
        } catch (_) {
          data = {};
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(data);
        } else {
          const error = new Error(data.message || `请求失败：${xhr.status}`);
          error.status = xhr.status;
          reject(error);
        }
      };
      xhr.onerror = () => reject(new Error("网络错误，上传失败"));
      xhr.send(formData);
    });
    userWorkspaceState.scopedData.resume_profile = payload.data || emptyResumeProfile();
    userWorkspaceState.scopedDataLoaded.resume_profile = true;
    resumeTaskState.forceInputView = true;
    renderResumeProfileSection(userWorkspaceState.scopedData.resume_profile);
    setResumeProgress("upload", 100, "已上传 100%", false);
    setTimeout(() => {
      if (!resumeTaskState.uploadInFlight) hideResumeProgress("upload");
    }, 1200);
    showToast("上传成功", "简历文件已保存。", "success", 1600);
    refreshUnifiedExperience();
  } catch (error) {
    setResumeProgress("upload", 0, "上传失败", false);
    showToast("上传失败", error.message, "error", 2200);
  } finally {
    resumeTaskState.uploadInFlight = false;
    updateResumeActionButtons();
    if (event?.target) event.target.value = "";
  }
}

async function onResumePdfSelected(event) {
  return onResumeFileSelected(event);
}

async function legacyAnalyzeResumeMatch() {
  if (resumeTaskState.uploadInFlight || resumeTaskState.analyzeInFlight) {
    showToast("请稍候", "当前有任务正在执行中。", "warning", 1800);
    return;
  }
  const jobDescription = getResumeJobDescription();
  const hasJobDescription = jobDescription.length > 0;
  resumeTaskState.analyzeInFlight = true;
  resumeTaskState.forceInputView = false;
  syncResumeJudgeFlow(getResumeProfileFromCache());
  updateResumeActionButtons();
  startAnalyzeProgressTicker();
  const analyzeStatus = document.getElementById("resumeAnalyzeStatus");
  const analyzeMeta = document.getElementById("resumeAnalyzeMeta");
  if (analyzeStatus) analyzeStatus.textContent = "排队中";
  if (analyzeMeta) analyzeMeta.textContent = "正在创建分析任务...";
  try {
    const startPayload = await requestJson("/api/resume/analyze/start", {
      method: "POST",
      body: { job_description: jobDescription }
    });
    const jobId = String(startPayload.job_id || "").trim();
    if (!jobId) throw new Error("分析任务创建失败：缺少任务 ID");

    const startedAt = Date.now();
    let statusPayload = null;
    for (let round = 0; round < 240; round += 1) {
      statusPayload = await requestJson(`/api/resume/analyze/status?job_id=${encodeURIComponent(jobId)}`);
      const job = statusPayload?.job || {};
      const elapsedSec = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      const status = String(job.status || "").trim();
      if (status === "success") break;
      if (status === "failed") {
        const resumeError = String(statusPayload?.resume?.error_message || "").trim();
        throw new Error(String(job.message || resumeError || "简历匹配分析失败"));
      }
      applyResumeAnalyzeRuntimeStatus(job, elapsedSec);
      await sleepMs(900);
    }

    const resumeData = statusPayload?.resume || null;
    if (!resumeData || String(statusPayload?.job?.status || "").trim() !== "success") {
      throw new Error("分析超时，请稍后在简历状态中查看结果。");
    }

    userWorkspaceState.scopedData.resume_profile = resumeData;
    userWorkspaceState.scopedDataLoaded.resume_profile = true;
    resumeTaskState.forceInputView = false;
    renderResumeProfileSection(userWorkspaceState.scopedData.resume_profile);
    setResumeProgress("analyze", 100, "分析完成", false);
    showToast("分析完成", hasJobDescription ? "简历匹配结果已更新。" : "简历诊断结果已更新。", "success", 1800);
    refreshUnifiedExperience();
  } catch (error) {
    resumeTaskState.forceInputView = true;
    syncResumeJudgeFlow(getResumeProfileFromCache());
    setResumeProgress("analyze", 0, "分析失败", false);
    showToast("分析失败", error.message, "error", 2600);
  } finally {
    resumeTaskState.analyzeInFlight = false;
    stopAnalyzeProgressTicker();
    updateResumeActionButtons();
  }
}

async function analyzeResumeMatch() {
  if (resumeTaskState.uploadInFlight || resumeTaskState.analyzeInFlight) {
    return legacyAnalyzeResumeMatch();
  }

  const jobDescription = getResumeJobDescription();
  const hasJobDescription = jobDescription.length > 0;
  resumeTaskState.analyzeInFlight = true;
  resumeTaskState.forceInputView = false;
  syncResumeJudgeFlow(getResumeProfileFromCache());
  updateResumeActionButtons();
  startAnalyzeProgressTicker();

  const analyzeStatus = document.getElementById("resumeAnalyzeStatus");
  const analyzeMeta = document.getElementById("resumeAnalyzeMeta");
  if (analyzeStatus) analyzeStatus.textContent = "排队中";
  if (analyzeMeta) analyzeMeta.textContent = "正在创建分析任务...";

  try {
    const startPayload = await requestJson("/api/resume/analyze/start", {
      method: "POST",
      body: { job_description: jobDescription }
    });
    const jobId = String(startPayload.job_id || "").trim();
    if (!jobId) throw new Error("分析任务创建失败：缺少任务 ID");

    const startedAt = Date.now();
    const maxPollRounds = 900;
    let statusPayload = null;

    for (let round = 0; round < maxPollRounds; round += 1) {
      statusPayload = await requestJson(`/api/resume/analyze/status?job_id=${encodeURIComponent(jobId)}`);
      const job = statusPayload?.job || {};
      const resumeData = statusPayload?.resume || null;
      const elapsedSec = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      const jobStatus = String(job.status || "").trim();
      const resumeStatus = String(resumeData?.status || "").trim();
      const resumeStage = String(resumeData?.analysis_meta?.stage || "").trim();
      const resumeSucceeded = resumeStatus === "analyzed" || resumeStage === "done";

      if (jobStatus === "success" || resumeSucceeded) break;

      if (jobStatus === "failed" && !resumeSucceeded) {
        const resumeError = String(resumeData?.error_message || "").trim();
        throw new Error(String(job.message || resumeError || "简历匹配分析失败"));
      }

      applyResumeAnalyzeRuntimeStatus(job, elapsedSec);
      await sleepMs(900);
    }

    let resumeData = statusPayload?.resume || null;
    let jobStatus = String(statusPayload?.job?.status || "").trim();
    let resumeStatus = String(resumeData?.status || "").trim();
    let resumeStage = String(resumeData?.analysis_meta?.stage || "").trim();
    let resumeSucceeded = resumeStatus === "analyzed" || resumeStage === "done";

    if (!resumeSucceeded && jobStatus !== "success") {
      const refreshedResume = await loadResumeProfile(true);
      resumeData = refreshedResume || resumeData;
      resumeStatus = String(resumeData?.status || "").trim();
      resumeStage = String(resumeData?.analysis_meta?.stage || "").trim();
      resumeSucceeded = resumeStatus === "analyzed" || resumeStage === "done";
    }

    if (!resumeData || !resumeSucceeded) {
      const stillRunning = resumeStatus === "analyzing" || resumeStage === "queued";
      if (stillRunning) {
        userWorkspaceState.scopedData.resume_profile = resumeData;
        userWorkspaceState.scopedDataLoaded.resume_profile = true;
        resumeTaskState.forceInputView = false;
        renderResumeProfileSection(userWorkspaceState.scopedData.resume_profile);
        setResumeProgress("analyze", 100, "后台继续分析中", true);
        showToast("任务仍在运行", "简历分析耗时较长，已转入后台继续处理。", "warning", 2600);
        return;
      }
      throw new Error("分析超时，请稍后在简历状态中查看结果。");
    }

    userWorkspaceState.scopedData.resume_profile = resumeData;
    userWorkspaceState.scopedDataLoaded.resume_profile = true;
    resumeTaskState.forceInputView = false;
    renderResumeProfileSection(userWorkspaceState.scopedData.resume_profile);
    setResumeProgress("analyze", 100, "分析完成", false);
    showToast("分析完成", hasJobDescription ? "简历匹配结果已更新。" : "简历诊断结果已更新。", "success", 1800);
    refreshUnifiedExperience();
  } catch (error) {
    const refreshedResume = await loadResumeProfile(true).catch(() => null);
    const resumeStatus = String(refreshedResume?.status || "").trim();
    const resumeStage = String(refreshedResume?.analysis_meta?.stage || "").trim();
    const resumeSucceeded = resumeStatus === "analyzed" || resumeStage === "done";

    if (resumeSucceeded) {
      userWorkspaceState.scopedData.resume_profile = refreshedResume;
      userWorkspaceState.scopedDataLoaded.resume_profile = true;
      resumeTaskState.forceInputView = false;
      renderResumeProfileSection(userWorkspaceState.scopedData.resume_profile);
      setResumeProgress("analyze", 100, "分析完成", false);
      showToast("分析完成", hasJobDescription ? "简历匹配结果已更新。" : "简历诊断结果已更新。", "success", 1800);
      refreshUnifiedExperience();
      return;
    }

    resumeTaskState.forceInputView = true;
    syncResumeJudgeFlow(getResumeProfileFromCache());
    setResumeProgress("analyze", 0, "分析失败", false);
    showToast("分析失败", error?.message || "简历分析失败", "error", 2600);
  } finally {
    resumeTaskState.analyzeInFlight = false;
    stopAnalyzeProgressTicker();
    updateResumeActionButtons();
  }
}

async function analyzeResumePdf() {
  return analyzeResumeMatch();
}

async function deleteResumeProfile() {
  if (!confirm("确认删除当前简历、JD 和分析结果？")) return;
  try {
    await requestJson("/api/resume/profile", { method: "DELETE" });
    userWorkspaceState.scopedData.resume_profile = null;
    userWorkspaceState.scopedDataLoaded.resume_profile = true;
    resumeTaskState.forceInputView = true;
    renderResumeProfileSection(emptyResumeProfile());
    toggleResumeJobInput(false);
    setResumeJobDescription("");
    showToast("已删除", "简历与分析结果已清空。", "success", 1600);
    refreshUnifiedExperience();
  } catch (error) {
    showToast("删除失败", error.message, "error", 2200);
  }
}
