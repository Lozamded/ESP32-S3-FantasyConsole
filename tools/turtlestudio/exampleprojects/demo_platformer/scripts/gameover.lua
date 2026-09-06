-- Script de la primera escena (scripts/intro.lua), corre en el actor invisible
-- "scene_controller" (objects/Objects/scene_controller.json) -- ver
-- spec/lua/object-script-v0.md "Cambio de escena".
-- Titulo, logo, menu, etc. El ENTRY del cartucho es scripts/global.lua (solo en proyecto TurtleStudio).

-- Indices de boton (spec/input-v0.md): 0-3 = LEFT/RIGHT/UP/DOWN, 4-7 = A/B/C/D.
function _update(dt)
  if btnp(4) or btnp(5) or btnp(6) or btnp(7) then
    state_set("lifes", 4) 
    state_set("gears",0)
    goto_scene("intro")
  end
end