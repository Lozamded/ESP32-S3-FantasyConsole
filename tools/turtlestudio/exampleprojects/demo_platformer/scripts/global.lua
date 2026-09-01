-- ENTRY por defecto: scripts/global.lua (arranque del cartucho)
print("Hola desde TurtleStudio (global)")
cls(1)
flip()

state_set("lifes", 4)  -- inicializa vidas al arrancar el cartucho (una sola vez)

function _hud(dt)
  local n = state_get("gears") or 0
  gui_layer_set_text("gametstatus", "gearsamount", "x" .. tostring(n))
  gui_layer_set_pips("gametstatus", "shells", state_get("hp") or 3)
  gui_layer_set_text("gametstatus", "lifesamount", "x" .. tostring(state_get("lifes") or 4))
end
