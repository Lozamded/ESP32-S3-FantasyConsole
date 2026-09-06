import React from 'react';
import ComponentCreator from '@docusaurus/ComponentCreator';

export default [
  {
    path: '/',
    component: ComponentCreator('/', '2e1'),
    exact: true
  },
  {
    path: '/',
    component: ComponentCreator('/', '48c'),
    routes: [
      {
        path: '/',
        component: ComponentCreator('/', '97d'),
        routes: [
          {
            path: '/',
            component: ComponentCreator('/', '9dc'),
            routes: [
              {
                path: '/assets/binary-formats',
                component: ComponentCreator('/assets/binary-formats', '02e'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/assets/sprite-spec',
                component: ComponentCreator('/assets/sprite-spec', '421'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/cartridge/turtlecart-format',
                component: ComponentCreator('/cartridge/turtlecart-format', 'dd3'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/gui/gui-layers',
                component: ComponentCreator('/gui/gui-layers', '9c2'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/gui/hud-border',
                component: ComponentCreator('/gui/hud-border', '521'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/hardware/audio',
                component: ComponentCreator('/hardware/audio', '4cd'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/hardware/rca-composite',
                component: ComponentCreator('/hardware/rca-composite', 'c96'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/intro',
                component: ComponentCreator('/intro', '9af'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/lua/animation',
                component: ComponentCreator('/lua/animation', '16f'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/lua/entry-vm',
                component: ComponentCreator('/lua/entry-vm', '764'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/lua/firmware-bridge',
                component: ComponentCreator('/lua/firmware-bridge', '7aa'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/lua/input',
                component: ComponentCreator('/lua/input', '71e'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/lua/object-scripts',
                component: ComponentCreator('/lua/object-scripts', '243'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/lua/overview',
                component: ComponentCreator('/lua/overview', 'c22'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/lua/physics',
                component: ComponentCreator('/lua/physics', '8f6'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/lua/scene-script',
                component: ComponentCreator('/lua/scene-script', 'b74'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/lua/state',
                component: ComponentCreator('/lua/state', '15a'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/scene/object-identity',
                component: ComponentCreator('/scene/object-identity', '19b'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/scene/scene-format',
                component: ComponentCreator('/scene/scene-format', 'eb3'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/scene/text-labels',
                component: ComponentCreator('/scene/text-labels', '4cd'),
                exact: true,
                sidebar: "mainSidebar"
              },
              {
                path: '/turtlestudio/guide',
                component: ComponentCreator('/turtlestudio/guide', '699'),
                exact: true,
                sidebar: "mainSidebar"
              }
            ]
          }
        ]
      }
    ]
  },
  {
    path: '*',
    component: ComponentCreator('*'),
  },
];
