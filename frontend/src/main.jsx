import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import DitApp from './dit/DitApp.jsx';
import './styles.css';

// /dit — страница конкурсного кейса ДИТ (Java API, варианты трассировки);
// всё остальное — исходный 3D-интерфейс хакатона.
const isDit = window.location.pathname.startsWith('/dit');

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {isDit ? <DitApp /> : <App />}
  </React.StrictMode>,
);
