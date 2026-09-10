// Паспорт объекта — плавающее окно справа поверх 3D-сцены.
// Открывается кликом по зданию в режиме «Объект», закрывается крестиком.

export default function PassportWindow({ passport, onConnectObject, onClose }) {
  if (!passport) return null;
  return (
    <div className="float-window float-right">
      <button className="float-close" onClick={onClose} title="Закрыть">✕</button>
      <h2>Паспорт объекта</h2>
      <p className="pp-title"><b>{passport.name}</b></p>
      <div className="pp-grid">
        <span>Этажность</span><b>{passport.floors}</b>
        <span>Площадь</span><b>{passport.area_m2} м²</b>
        <span>Отметка земли</span><b>{passport.ground_z_m} м</b>
        <span>Тепловая нагрузка</span><b>{passport.heat_load_kw} кВт</b>
      </div>
      {passport.network && (
        <>
          <h2>Коммуникации</h2>
          <p className="impact">
            ⌁ {passport.network.name}<br />
            <small>расстояние {passport.network.distance_m} м до точки врезки</small>
          </p>
        </>
      )}
      {passport.roads.length > 0 && (
        <p className="pp-roads">
          Дороги рядом: {passport.roads.map((r) => `${r.name} (${r.distance_m} м)`).join(', ')}
        </p>
      )}
      {passport.zones.length > 0 && (
        <p className="error">⚠ Охранные зоны: {passport.zones.join('; ')}</p>
      )}
      {passport.network && (
        <button onClick={onConnectObject}>
          ⌁ Проложить трассу к этому объекту
        </button>
      )}
    </div>
  );
}
