async function checkHealth() {
  const node = document.querySelector("#health");
  if (!node) return;
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    const ready = response.ok && data.model_ready;
    node.textContent = ready ? "Local model ready" : "Ollama needs attention";
    node.className = `health ${ready ? "ready" : "error"}`;
    node.title = data.detail || (ready ? "Configured model is available" : "Install the configured model");
  } catch (error) {
    node.textContent = "Server unavailable";
    node.className = "health error";
  }
}

async function pollJob(jobId, statusNode) {
  for (;;) {
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (!response.ok) throw new Error("Could not read job status");
    const job = await response.json();
    statusNode.textContent = `${job.stage}: ${job.message || job.status} (${job.progress}%)`;
    statusNode.hidden = false;
    if (job.status === "completed") {
      window.location.reload();
      return;
    }
    if (job.status === "failed") {
      statusNode.textContent = `Stage failed: ${job.error || "Unknown error"}`;
      statusNode.classList.add("error");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

document.addEventListener("DOMContentLoaded", () => {
  checkHealth();
  const button = document.querySelector(".run-stage");
  if (button) button.addEventListener("click", async () => {
    const statusNode = document.querySelector("#job-status");
    button.disabled = true;
    statusNode.hidden = false;
    statusNode.textContent = "Queueing stage…";
    try {
      const response = await fetch(
        `/api/projects/${button.dataset.project}/stages/${button.dataset.stage}`,
        { method: "POST" },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not start stage");
      await pollJob(data.job_id, statusNode);
    } catch (error) {
      statusNode.textContent = error.message;
      statusNode.classList.add("error");
      button.disabled = false;
    }
  });

  const upload = document.querySelector("#dataset-upload");
  if (upload) upload.addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.querySelector("#dataset-status");
    status.textContent = "Uploading and validating encoding…";
    try {
      const response = await fetch(
        `/api/projects/${upload.dataset.project}/datasets`,
        { method: "POST", body: new FormData(upload) },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Upload failed");
      status.textContent = `Stored ${data.filename} (${data.size_bytes} bytes). Reloading…`;
      window.location.reload();
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
    }
  });

  const experiment = document.querySelector("#experiment-run");
  if (experiment) experiment.addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.querySelector("#experiment-status");
    const fields = new FormData(experiment);
    let operation;
    try {
      operation = JSON.parse(fields.get("operation"));
    } catch (_) {
      status.textContent = "Operation must be valid JSON.";
      return;
    }
    status.textContent = "Running approved bounded experiment…";
    const payload = {
      dataset_artifact_id: Number(fields.get("dataset_artifact_id")),
      experiment_id: fields.get("experiment_id"),
      approved_by_user: fields.get("approved") === "on",
      operation,
    };
    try {
      const response = await fetch(
        `/api/projects/${experiment.dataset.project}/experiments/run`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Experiment failed");
      status.textContent = JSON.stringify(data, null, 2);
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
    }
  });
});
