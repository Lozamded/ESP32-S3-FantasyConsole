-- Script de escena de Lvl_1 (scenes/Lvl_1.json declara "script": "Lvl_1") --
-- ver spec/lua/scene-script-v0.md.

-- Habilita el menu de pausa (START) en esta escena. La VM de escena no puede mostrar
-- capas GUI ni corre mientras la pausa esta activa, asi que el toggle vive en el _hud
-- de scripts/global.lua; aca solo avisamos "esta escena admite pausa". _hud_init lo
-- vuelve a 0 al comenzar cada escena, y este _update corre antes que _hud en el tick.
function _update(dt)
  state_set("pause_enabled", 1)
end
