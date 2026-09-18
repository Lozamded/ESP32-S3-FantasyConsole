-- Script de la primera escena (scripts/intro.lua): corre como script de escena
-- (scenes/intro.json declara "script": "intro") -- ver spec/lua/scene-script-v0.md.
-- Titulo, logo, menu, etc. El ENTRY del cartucho es scripts/global.lua (solo en proyecto TurtleStudio).

-- Indices de boton (spec/input-v0.md): 0-3 = LEFT/RIGHT/UP/DOWN, 4-7 = A/B/C/D.

local LANGUAGES = {"en", "es"}

local function lang_index()
  local current = get_lang()
  for i, code in ipairs(LANGUAGES) do
    if code == current then return i end
  end
  return 1
end

function _update(dt)
  if btnp(2) then  -- UP: idioma anterior
    local i = lang_index() - 1
    if i < 1 then i = #LANGUAGES end
    set_lang(LANGUAGES[i])
    restart_scene()
    return
  end
  if btnp(3) then  -- DOWN: idioma siguiente
    local i = lang_index() % #LANGUAGES + 1
    set_lang(LANGUAGES[i])
    restart_scene()
    return
  end
  if btnp(4) or btnp(5) or btnp(6) or btnp(7) then
    goto_scene("Lvl_1")
  end
end
