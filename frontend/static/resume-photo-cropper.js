(() => {
  const picker = document.getElementById("resumePickPhoto");
  const fileInput = document.getElementById("resumePhotoFile");
  const status = document.getElementById("resumePhotoStatus");
  const dialog = document.getElementById("resumePhotoCrop");
  const canvas = document.getElementById("resumePhotoCanvas");
  const zoom = document.getElementById("resumePhotoZoom");
  const ctx = canvas.getContext("2d");
  const { width, height } = canvas;
  let selection = 0;
  let crop = null;
  let drag = null;

  function clamp(value, extent) {
    return Math.max(-extent, Math.min(extent, value));
  }

  function render() {
    const scale = crop.cover * crop.zoom;
    const w = crop.image.naturalWidth * scale;
    const h = crop.image.naturalHeight * scale;
    crop.x = clamp(crop.x, Math.max(0, (w - width) / 2));
    crop.y = clamp(crop.y, Math.max(0, (h - height) / 2));
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(crop.image, (width - w) / 2 + crop.x, (height - h) / 2 + crop.y, w, h);
  }

  picker.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    fileInput.value = "";
    if (!file) return;
    const current = ++selection;
    status.textContent = "";
    if (!/^(image\/(jpeg|png|webp))$/.test(file.type) || file.size > 12 * 1024 * 1024) {
      status.textContent = "请选择不超过 12 MB 的 JPG、PNG 或 WebP 图片。";
      return;
    }
    const source = URL.createObjectURL(file);
    const image = new Image();
    try {
      image.src = source;
      await image.decode();
      if (current !== selection) return;
      if (!ctx || !image.naturalWidth || !image.naturalHeight || image.naturalWidth * image.naturalHeight > 24_000_000) {
        status.textContent = "无法裁剪这张图片，请选择不超过 2400 万像素的图片。";
        return;
      }
      crop = {
        image, source, x: 0, y: 0, zoom: 1,
        cover: Math.max(width / image.naturalWidth, height / image.naturalHeight)
      };
      zoom.value = "1";
      render();
      dialog.showModal();
      canvas.focus();
    } catch {
      if (current === selection) status.textContent = "图片无法打开，请重新选择。";
    } finally {
      if (crop?.source !== source || !dialog.open) {
        if (crop?.source === source) crop = null;
        URL.revokeObjectURL(source);
      }
    }
  });

  zoom.addEventListener("input", () => {
    if (!crop) return;
    const next = Number(zoom.value);
    crop.x *= next / crop.zoom;
    crop.y *= next / crop.zoom;
    crop.zoom = next;
    render();
  });
  document.getElementById("resumePhotoReset").addEventListener("click", () => {
    if (!crop) return;
    crop.x = crop.y = 0;
    crop.zoom = 1;
    zoom.value = "1";
    render();
  });

  canvas.addEventListener("pointerdown", event => {
    if (!crop || event.button !== 0 || drag) return;
    canvas.setPointerCapture(event.pointerId);
    drag = { id: event.pointerId, x: event.clientX, y: event.clientY };
  });
  canvas.addEventListener("pointermove", event => {
    if (!crop || drag?.id !== event.pointerId) return;
    const rect = canvas.getBoundingClientRect();
    crop.x += (event.clientX - drag.x) * width / rect.width;
    crop.y += (event.clientY - drag.y) * height / rect.height;
    drag.x = event.clientX;
    drag.y = event.clientY;
    render();
  });
  canvas.addEventListener("lostpointercapture", () => { drag = null; });
  const movement = { ArrowLeft: [-4, 0], ArrowRight: [4, 0], ArrowUp: [0, -4], ArrowDown: [0, 4] };
  canvas.addEventListener("keydown", event => {
    if (!crop || !Object.hasOwn(movement, event.key)) return;
    event.preventDefault();
    const [x, y] = movement[event.key];
    crop.x += x;
    crop.y += y;
    render();
  });

  document.getElementById("resumeApplyPhoto").addEventListener("click", () => {
    if (!crop) return;
    let photo = canvas.toDataURL("image/jpeg", .92).split(",")[1];
    if (photo.length > 48000) photo = canvas.toDataURL("image/jpeg", .77).split(",")[1];
    picker.dispatchEvent(new CustomEvent("resume:photo-cropped", { detail: photo }));
    dialog.close();
  });
  dialog.querySelectorAll("[data-crop-close]").forEach(button => button.addEventListener("click", () => dialog.close()));
  dialog.addEventListener("close", () => {
    if (crop) URL.revokeObjectURL(crop.source);
    crop = null;
    drag = null;
    ctx?.clearRect(0, 0, width, height);
    picker.focus();
  });
})();
