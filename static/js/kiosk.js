// Терминал на служебном входе: снимает 3 кадра и отправляет их на сервер.
(function () {
  const params = new URLSearchParams(location.search);
  if (params.get('key')) {            // ключ точки прохода выдается администратором один раз
    localStorage.setItem('kioskKey', params.get('key'));
    history.replaceState(null, '', location.pathname);
  }
  const key = localStorage.getItem('kioskKey') || '';
  const video = document.getElementById('video');
  const result = document.getElementById('result');
  const btn = document.getElementById('go');
  const FRAMES = 3, GAP_MS = 250;
  let busy = false;

  function show(text, cls) { result.className = 'result mt-3 ' + (cls || ''); result.textContent = text; }
  setInterval(() => { document.getElementById('clock').textContent = new Date().toLocaleString('ru-RU'); }, 1000);

  if (!key) { show('Терминал не зарегистрирован: откройте ссылку с ключом точки прохода.', 'err'); btn.disabled = true; }

  navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: 'user' }, audio: false })
    .then(s => { video.srcObject = s; })
    .catch(() => show('Камера недоступна. Используйте отметку по табельному номеру.', 'err'));

  function grab() {
    const c = document.createElement('canvas');
    c.width = video.videoWidth || 640; c.height = video.videoHeight || 480;
    c.getContext('2d').drawImage(video, 0, 0, c.width, c.height);
    return new Promise(r => c.toBlob(r, 'image/jpeg', 0.9));
  }

  async function mark() {
    if (busy || !key) return;
    busy = true; btn.disabled = true; show('Проверяем…');
    try {
      const fd = new FormData();
      for (let i = 0; i < FRAMES; i++) {
        fd.append('frames', await grab(), 'frame' + i + '.jpg');
        await new Promise(r => setTimeout(r, GAP_MS));
      }
      const resp = await fetch('/api/kiosk/recognize/', { method: 'POST', body: fd, headers: { 'X-Kiosk-Key': key } });
      const d = await resp.json();
      if (d.decision === 'accept') {
        show((d.repeated ? 'Вы уже отмечены: ' : '') + d.employee + ' – ' + d.direction.toLowerCase() + ' ' + d.time, 'ok');
      } else if (d.decision === 'review') {
        show(d.message, 'warn');
      } else {
        show(d.message || 'Ошибка', 'err');
      }
    } catch (e) {
      show('Нет связи с сервером. Повторите или отметьтесь по табельному номеру.', 'err');
    } finally {
      setTimeout(() => { busy = false; btn.disabled = false; }, 2500);
    }
  }
  btn.addEventListener('click', mark);
  document.addEventListener('keydown', e => { if (e.code === 'Space') mark(); });

  document.getElementById('fb').addEventListener('click', e => {
    e.preventDefault(); document.getElementById('fbform').style.display = 'flex';
  });
  document.getElementById('fbform').addEventListener('submit', async e => {
    e.preventDefault();
    const resp = await fetch('/api/kiosk/fallback/', { method: 'POST', body: new FormData(e.target), headers: { 'X-Kiosk-Key': key } });
    const d = await resp.json();
    show(d.ok ? d.employee + ': ' + d.message : d.message, d.ok ? 'warn' : 'err');
    e.target.reset(); e.target.style.display = 'none';
  });
})();
