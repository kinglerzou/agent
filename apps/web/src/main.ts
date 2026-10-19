import { createApp } from 'vue';
import App from './App.vue';
import GameOps from './GameOps.vue';
import './game.css';
import './style.css';

// eslint-disable-next-line @typescript-eslint/no-unsafe-argument -- vue-tsc checks the SFC type; ESLint sees an untyped import.
createApp(new URLSearchParams(location.search).has('studio') ? App : GameOps).mount('#app');
