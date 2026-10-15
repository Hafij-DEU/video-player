"""GLSL fragment shaders for the glshader element.

glshader supplies `tex` (the frame), `v_texcoord`, and the uniforms
`time`, `width` and `height`. Every shader keeps the GLSL ES 1.00 subset so it
runs on desktop GL and GLES drivers alike.
"""

HEADER = """#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float time;
uniform float width;
uniform float height;
"""

PASSTHROUGH = HEADER + """
void main () {
  gl_FragColor = texture2D (tex, v_texcoord);
}
"""

_BODIES = {
    "Grayscale": """
void main () {
  vec4 c = texture2D (tex, v_texcoord);
  float y = dot (c.rgb, vec3 (0.2126, 0.7152, 0.0722));
  gl_FragColor = vec4 (vec3 (y), c.a);
}
""",
    "Sepia": """
void main () {
  vec4 c = texture2D (tex, v_texcoord);
  vec3 s = vec3 (dot (c.rgb, vec3 (0.393, 0.769, 0.189)),
                 dot (c.rgb, vec3 (0.349, 0.686, 0.168)),
                 dot (c.rgb, vec3 (0.272, 0.534, 0.131)));
  gl_FragColor = vec4 (min (s, 1.0), c.a);
}
""",
    "Invert": """
void main () {
  vec4 c = texture2D (tex, v_texcoord);
  gl_FragColor = vec4 (1.0 - c.rgb, c.a);
}
""",
    "Sharpen": """
void main () {
  vec2 px = vec2 (1.0 / width, 1.0 / height);
  vec4 c = texture2D (tex, v_texcoord);
  vec4 n = texture2D (tex, v_texcoord + vec2 (0.0, -px.y))
         + texture2D (tex, v_texcoord + vec2 (0.0, px.y))
         + texture2D (tex, v_texcoord + vec2 (-px.x, 0.0))
         + texture2D (tex, v_texcoord + vec2 (px.x, 0.0));
  gl_FragColor = vec4 (clamp (c.rgb * 1.8 - n.rgb * 0.2, 0.0, 1.0), c.a);
}
""",
    "Soften": """
void main () {
  vec2 px = vec2 (1.0 / width, 1.0 / height);
  vec4 sum = vec4 (0.0);
  for (int x = -1; x <= 1; x++)
    for (int y = -1; y <= 1; y++)
      sum += texture2D (tex, v_texcoord + vec2 (float (x), float (y)) * px);
  gl_FragColor = sum / 9.0;
}
""",
    "Edge detect": """
float lum (vec2 o) {
  return dot (texture2D (tex, v_texcoord + o).rgb, vec3 (0.299, 0.587, 0.114));
}
void main () {
  vec2 px = vec2 (1.0 / width, 1.0 / height);
  float gx = lum (vec2 (px.x, 0.0)) - lum (vec2 (-px.x, 0.0));
  float gy = lum (vec2 (0.0, px.y)) - lum (vec2 (0.0, -px.y));
  gl_FragColor = vec4 (vec3 (clamp (length (vec2 (gx, gy)) * 4.0, 0.0, 1.0)), 1.0);
}
""",
    "Night vision": """
void main () {
  vec4 c = texture2D (tex, v_texcoord);
  float y = dot (c.rgb, vec3 (0.299, 0.587, 0.114));
  float grain = fract (sin (dot (v_texcoord * (time + 1.0), vec2 (12.9898, 78.233))) * 43758.5453);
  float vig = 1.0 - distance (v_texcoord, vec2 (0.5)) * 1.2;
  gl_FragColor = vec4 (vec3 (0.1, 1.0, 0.2) * (y * 1.4 + grain * 0.08) * vig, 1.0);
}
""",
    "Vignette": """
void main () {
  vec4 c = texture2D (tex, v_texcoord);
  float d = distance (v_texcoord, vec2 (0.5));
  gl_FragColor = vec4 (c.rgb * smoothstep (0.8, 0.35, d), c.a);
}
""",
    "Warm": """
void main () {
  vec4 c = texture2D (tex, v_texcoord);
  gl_FragColor = vec4 (min (c.rgb * vec3 (1.08, 1.0, 0.88), 1.0), c.a);
}
""",
    "Cool": """
void main () {
  vec4 c = texture2D (tex, v_texcoord);
  gl_FragColor = vec4 (min (c.rgb * vec3 (0.9, 1.0, 1.1), 1.0), c.a);
}
""",
}

SHADERS = {name: HEADER + body for name, body in _BODIES.items()}
