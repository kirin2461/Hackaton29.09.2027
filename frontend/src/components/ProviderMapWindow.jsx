// Синхронная карта Яндекс/2ГИС — плавающее окно поверх 3D-сцены.
//
// Юридически чистая интеграция: карта отображается через официальные
// JS API провайдеров (их виджет, их данные, их атрибуция). Геометрия
// из них НЕ извлекается — лицензии 2ГИС/Яндекса разрешают только
// отображение, что мы и делаем. Ключи бесплатные:
//   Яндекс — developer.tech.yandex.ru (JavaScript API)
//   2ГИС   — dev.2gis.ru (MapGL JS)

import { useEffect, useRef, useState } from 'react';
import { fetchGeoCenter, postToWgs84 } from '../api/client.js';

const LS_KEY = 'provider-map-key';

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) { existing.addEventListener('load', resolve); resolve(); return; }
    const el = document.createElement('script');
    el.src = src;
    el.onload = resolve;
    el.onerror = () => reject(new Error('не удалось загрузить API провайдера'));
    document.head.appendChild(el);
  });
}

export default function ProviderMapWindow({ provider, onProviderChange,
                                            getCameraTarget, onClose }) {
  const [key, setKey] = useState(localStorage.getItem(`${LS_KEY}:${provider}`) ?? '');
  const [status, setStatus] = useState('key'); // key | loading | ready | error
  const [error, setError] = useState(null);
  const mapEl = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);

  // При смене провайдера подставляем его сохранённый ключ.
  useEffect(() => {
    setKey(localStorage.getItem(`${LS_KEY}:${provider}`) ?? '');
    setStatus('key');
    if (mapRef.current?.destroy) mapRef.current.destroy();
    mapRef.current = null;
    markerRef.current = null;
    if (mapEl.current) mapEl.current.innerHTML = '';
  }, [provider]);

  const initMap = async () => {
    if (!key.trim()) { setError('Вставьте API-ключ'); return; }
    localStorage.setItem(`${LS_KEY}:${provider}`, key.trim());
    setStatus('loading');
    setError(null);
    try {
      if (mapEl.current) mapEl.current.innerHTML = '';
      const geo = await fetchGeoCenter();
      const [lon, lat] = geo.center;
      if (provider === 'yandex') {
        await loadScript(
          `https://api-maps.yandex.ru/2.1/?apikey=${encodeURIComponent(key.trim())}&lang=ru_RU`);
        await new Promise((res) => window.ymaps.ready(res));
        mapRef.current = new window.ymaps.Map(mapEl.current, {
          center: [lat, lon],
          zoom: 15,
          controls: ['zoomControl', 'typeSelector'],
        });
        // Гибрид со спутником — нагляднее всего для сверки с 3D.
        mapRef.current.setType('yandex#hybrid');
        markerRef.current = new window.ymaps.Placemark([lat, lon]);
        mapRef.current.geoObjects.add(markerRef.current);
      } else {
        await loadScript('https://mapgl.2gis.com/api/js/v1');
        mapRef.current = new window.mapgl.Map(mapEl.current, {
          center: [lon, lat],
          zoom: 15.5,
          key: key.trim(),
        });
        markerRef.current = new window.mapgl.Marker(mapRef.current, {
          coordinates: [lon, lat],
        });
      }
      setStatus('ready');
    } catch (e) {
      setStatus('error');
      setError(e.message);
    }
  };

  // Кнопка «⟳ к камере»: центр окна = точка, куда смотрит 3D-камера.
  const syncToCamera = async () => {
    if (!mapRef.current || !getCameraTarget) return;
    const [x, y] = getCameraTarget();
    try {
      const { lon, lat } = await postToWgs84(x, y);
      if (provider === 'yandex') {
        mapRef.current.panTo([lat, lon], { duration: 300 });
        markerRef.current?.geometry.setCoordinates([lat, lon]);
      } else {
        mapRef.current.setCenter([lon, lat]);
        markerRef.current?.setCoordinates([lon, lat]);
      }
    } catch { /* сеть — просто не двигаем карту */ }
  };

  return (
    <div className="float-window float-map">
      <button className="float-close" onClick={onClose} title="Закрыть">✕</button>
      <div className="map-tabs">
        <button
          className={provider === 'yandex' ? 'active' : ''}
          onClick={() => onProviderChange('yandex')}
        >
          Яндекс
        </button>
        <button
          className={provider === '2gis' ? 'active' : ''}
          onClick={() => onProviderChange('2gis')}
        >
          2ГИС
        </button>
        {status === 'ready' && (
          <button onClick={syncToCamera} title="Центрировать на точке 3D-камеры">
            ⟳ к камере
          </button>
        )}
      </div>
      {status !== 'ready' && (
        <div className="map-key-form">
          <input
            placeholder={provider === 'yandex'
              ? 'API-ключ Яндекс (JavaScript API)'
              : 'API-ключ 2ГИС (MapGL)'}
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
          <button disabled={status === 'loading'} onClick={initMap}>
            {status === 'loading' ? '⏳ Загрузка…' : 'Показать карту'}
          </button>
          <p className="hint">
            Бесплатный ключ: {provider === 'yandex'
              ? 'developer.tech.yandex.ru → JavaScript API'
              : 'dev.2gis.ru → MapGL JS'}.
            Карта — официальный виджет провайдера: данные отображаются,
            но не извлекаются (лицензия).
          </p>
          {error && <p className="error">{error}</p>}
        </div>
      )}
      <div
        ref={mapEl}
        className="provider-map"
        style={{ display: status === 'ready' || status === 'loading' ? 'block' : 'none' }}
      />
    </div>
  );
}
