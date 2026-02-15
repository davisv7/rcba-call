let mediaRecorder, chunks = [], blob, recording = false;
let timerInterval, timerStart;

const btnRecord = document.getElementById('btn-record');
const btnSave = document.getElementById('btn-save');
const preview = document.getElementById('preview');
const status = document.getElementById('rec-status');
const recTimer = document.getElementById('rec-timer');
const btnCancel = document.getElementById('btn-cancel');

const fmt = s => { s = Math.floor(s || 0); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
function setIcon(btn, name) {
  btn.innerHTML = '<i data-lucide="' + name + '"></i>';
  lucide.createIcons({ nodes: [btn] });
}

function initPlayer(container) {
  const audio = container.querySelector('audio');
  const btn = container.querySelector('.ap-play');
  const cur = container.querySelector('.ap-cur');
  const dur = container.querySelector('.ap-dur');
  const track = container.querySelector('.ap-track');
  const prog = container.querySelector('.ap-progress');

  audio.addEventListener('loadedmetadata', () => dur.textContent = fmt(audio.duration));
  audio.addEventListener('timeupdate', () => {
    cur.textContent = fmt(audio.currentTime);
    if (audio.duration) prog.style.width = (audio.currentTime / audio.duration * 100) + '%';
  });
  audio.addEventListener('ended', () => { setIcon(btn, 'play'); });

  btn.addEventListener('click', () => {
    document.querySelectorAll('.audio-player audio').forEach(a => {
      if (a !== audio && !a.paused) { a.pause(); setIcon(a.parentElement.querySelector('.ap-play'), 'play'); }
    });
    if (audio.paused) { audio.play(); setIcon(btn, 'pause'); }
    else { audio.pause(); setIcon(btn, 'play'); }
  });

  track.addEventListener('click', e => {
    if (audio.duration) {
      audio.currentTime = (e.offsetX / track.offsetWidth) * audio.duration;
    }
  });
}

btnRecord.addEventListener('click', async () => {
  if (recording) {
    mediaRecorder.stop();
    return;
  }
  chunks = [];
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.ondataavailable = e => chunks.push(e.data);
  mediaRecorder.onstop = () => {
    recording = false;
    clearInterval(timerInterval);
    stream.getTracks().forEach(t => t.stop());
    blob = new Blob(chunks, { type: 'audio/webm' });
    const url = URL.createObjectURL(blob);
    preview.innerHTML =
      '<div class="audio-player">' +
        '<button class="ap-btn ap-play" type="button"><i data-lucide="play"></i></button>' +
        '<span class="ap-time ap-cur">0:00</span>' +
        '<div class="ap-track"><div class="ap-progress"></div></div>' +
        '<span class="ap-time ap-dur">0:00</span>' +
        '<audio src="' + url + '"></audio>' +
      '</div>';
    lucide.createIcons({ nodes: [preview] });
    initPlayer(preview.querySelector('.audio-player'));
    btnSave.disabled = false;
    btnSave.style.display = '';
    btnCancel.style.display = '';
    btnRecord.textContent = 'Re-record';
    recTimer.style.display = 'none';
    status.textContent = 'Preview your recording, then click Save.';
  };
  mediaRecorder.start();
  recording = true;
  btnRecord.textContent = 'Stop Recording';
  preview.innerHTML = '';
  btnSave.style.display = 'none';
  btnCancel.style.display = 'none';
  status.textContent = 'Recording...';

  // Start timer
  timerStart = Date.now();
  recTimer.textContent = '0:00';
  recTimer.style.display = '';
  timerInterval = setInterval(() => {
    recTimer.textContent = fmt((Date.now() - timerStart) / 1000);
  }, 250);
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

btnCancel.addEventListener('click', () => {
  blob = null;
  preview.innerHTML = '';
  btnSave.style.display = 'none';
  btnSave.disabled = true;
  btnCancel.style.display = 'none';
  btnRecord.textContent = 'Start Recording';
  status.textContent = '';
});
