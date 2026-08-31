-- ENTRY por defecto: scripts/global.lua (arranque del cartucho)
print("Hola desde TurtleStudio (global)")
cls(1)
flip()

function _hud(dt)
  local n = state_get("gears") or 0
  gui_layer_set_text("gametstatus", "gearsamount", "x" .. tostring(n))
  gui_layer_set_pips("gametstatus", "shells", state_get("hp") or 3)
end
