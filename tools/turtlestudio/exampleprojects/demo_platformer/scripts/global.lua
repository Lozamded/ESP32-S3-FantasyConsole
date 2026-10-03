-- ENTRY por defecto: scripts/global.lua (arranque del cartucho)
print("Hola desde TurtleStudio (global)")
cls(1)
flip()

state_set("lifes", 4)  -- inicializa vidas al arrancar el cartucho (una sola vez)

local BTN_START = 8  -- spec/input-v0.md

function _hud_init()
  -- Cada escena arranca sin pausa; solo las que lo habilitan (scripts/Lvl_1.lua) la admiten.
  state_set("pause_enabled", 0)
end

function _hud(dt)
  -- START alterna el menu de pausa. pause_layer tiene pauses_scene=true: mientras esta
  -- visible no corren los _update de actores ni de escena, pero _hud si (por eso vive aca).
  -- btnp se consume siempre para que un START de otra escena no quede retenido.
  if btnp(BTN_START) and state_get("pause_enabled") == 1 then
    if gui_layer_visible("pause_layer") then
      gui_layer_hide("pause_layer")
    else
      gui_layer_show("pause_layer")
    end
  end

  local n = state_get("gears") or 0
  gui_layer_set_text("gametstatus", "gearsamount", "x" .. tostring(n))
  gui_layer_set_pips("gametstatus", "shells", state_get("hp") or 3)
  gui_layer_set_text("gametstatus", "lifesamount", "x" .. tostring(state_get("lifes") or 4))
end
