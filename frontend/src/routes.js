import ProxyManager from './components/ProxyManager';

// ...existing code...

const routes = [
  ...existingRoutes,
  {
    path: '/proxy',
    element: <ProxyManager />,
    name: 'Proxy Manager',
  },
];

export default routes;
