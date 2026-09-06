// @ts-check

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  mainSidebar: [
    'intro',
    {
      type: 'category',
      label: 'Cartridge Format',
      items: ['cartridge/turtlecart-format'],
    },
    {
      type: 'category',
      label: 'Scene Format',
      items: [
        'scene/scene-format',
        'scene/text-labels',
        'scene/object-identity',
      ],
    },
    {
      type: 'category',
      label: 'Lua Scripting API',
      items: [
        'lua/overview',
        'lua/entry-vm',
        'lua/object-scripts',
        'lua/animation',
        'lua/physics',
        'lua/input',
        'lua/scene-script',
        'lua/state',
        'lua/firmware-bridge',
      ],
    },
    {
      type: 'category',
      label: 'Assets',
      items: ['assets/sprite-spec', 'assets/binary-formats'],
    },
    {
      type: 'category',
      label: 'GUI',
      items: ['gui/hud-border', 'gui/gui-layers'],
    },
    {
      type: 'category',
      label: 'TurtleStudio',
      items: ['turtlestudio/guide'],
    },
    {
      type: 'category',
      label: 'Hardware',
      items: ['hardware/audio', 'hardware/rca-composite'],
    },
  ],
};

module.exports = sidebars;
