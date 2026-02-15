let mediaRecorder, chunks = [], blob;

const btnRecord = document.getElementById('btn-record');
const btnStop = document.getElementById('btn-stop');
const btnSave = document.getElementById('btn-save');
const preview = document.getElementById('preview');
const status = document.getElementById('rec-status');

btnRecord.addEventListener('click', async () => {
  chunks = [];
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.ondataavailable = e => chunks.push(e.data);
  mediaRecorder.onstop = () => {
    stream.getTracks().forEach(t => t.stop());
    blob = new Blob(chunks, { type: 'audio/webm' });
    const url = URL.createObjectURL(blob);
    preview.innerHTML = `<audio controls src="${url}"></audio>`;
    btnSave.disabled = false;
    status.textContent = 'Preview your recording, then click Save.';
  };
  mediaRecorder.start();
  btnRecord.disabled = true;
  btnStop.disabled = false;
  status.textContent = 'Recording...';
});

btnStop.addEventListener('click', () => {
  mediaRecorder.stop();
  btnStop.disabled = true;
  btnRecord.disabled = false;
});

btnSave.addEventListener('click', async () => {
  const name = document.getElementById('rec-name').value || 'Untitled';
  const fd = new FormData();
  fd.append('name', name);
  fd.append('audio', blob, 'recording.webm');
  btnSave.disabled = true;
  status.textContent = 'Uploading & converting...';
  const res = await fetch('/api/recordings', { method: 'POST', body: fd });
  if (res.ok) {
    status.textContent = 'Saved!';
    location.reload();
  } else {
    const err = await res.json();
    status.textContent = 'Error: ' + (err.error || 'unknown');
    btnSave.disabled = false;
  }
});
