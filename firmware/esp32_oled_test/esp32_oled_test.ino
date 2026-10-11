// ESP32 DevKit V1 + 1.3" SH1106 OLED: still test screens for the glasses
// projection optics. Same wiring and library as firmware/esp32_hud, so the
// display can stay connected when switching between the two sketches.
//
// Screens (each is drawn once and held still, so focus can be judged):
//   0 align       border, corner marks, centre cross, TOP / L / R markers
//   1 text sizes  one sentence in five font sizes; B is the size of ring labels
//   2 ring        the real HUD layout with sample labels
//   3 grid        16 px lines and 8 px dots, for distortion and edge focus
//   4 checker     4 px squares, for sharpness and contrast
//   5 white       every pixel on, for brightness, glare and ghost images
//   6 big word    one large word and a small sentence
//
// Controls: press the BOOT button for the next screen, or send one character
// over USB Serial at 115200 baud:
//   n / p   next / previous screen        0-6  jump to a screen
//   f       flip: normal, mirror left-right, mirror top-bottom, rotate 180
//   b       brightness: full, half, low, minimum
//   i       invert (dark on light)        a    change screen every 4 s
// Once the picture reads correctly through the optics, copy the flip setting
// into FLIP_MODE in firmware/esp32_hud/esp32_hud.ino.
//
// Library (Arduino Library Manager): "U8g2" by oliver.
// Wiring: OLED SDA -> GPIO 21, SCK/SCL -> GPIO 22, VCC -> 3V3, GND -> GND.

#include <U8g2lib.h>
#include <Wire.h>
#include <math.h>

U8G2_SH1106_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

const int W = 128, H = 64;
const int BOOT_BTN = 0;
const unsigned long AUTO_MS = 4000;

const int PAGES = 7;
const char* PAGE_NAMES[PAGES] = {"align", "text sizes", "ring", "grid", "checker", "white", "big word"};
const int FLIPS = 4;
const u8g2_cb_t* FLIP_MODES[FLIPS] = {U8G2_R0, U8G2_MIRROR, U8G2_MIRROR_VERTICAL, U8G2_R2};
const char* FLIP_NAMES[FLIPS] = {"normal", "mirror L-R", "mirror T-B", "rotate 180"};
const int LEVELS = 4;
const uint8_t LEVEL_VALUES[LEVELS] = {255, 128, 40, 1};
const char* LEVEL_NAMES[LEVELS] = {"full", "half", "low", "minimum"};

// ---------- State ----------
int page = 0, flip = 0, level = 0;
bool inverted = false, autoCycle = false, dirty = true;
unsigned long lastChange = 0, lastPress = 0;
bool lastBtn = HIGH;

// Centre a string on x; y is the text baseline.
void centered(const char* s, int x, int y) {
  u8g2.drawStr(x - u8g2.getStrWidth(s) / 2, y, s);
}

// ---------- Screens ----------
void drawAlign() {
  u8g2.drawFrame(0, 0, W, H);                       // outermost pixels: is anything cropped?
  const int M = 4, L = 8;
  u8g2.drawHLine(M, M, L);            u8g2.drawVLine(M, M, L);
  u8g2.drawHLine(W - M - L, M, L);    u8g2.drawVLine(W - M - 1, M, L);
  u8g2.drawHLine(M, H - M - 1, L);    u8g2.drawVLine(M, H - M - L, L);
  u8g2.drawHLine(W - M - L, H - M - 1, L); u8g2.drawVLine(W - M - 1, H - M - L, L);
  u8g2.drawHLine(W / 2 - 10, H / 2, 21);
  u8g2.drawVLine(W / 2, H / 2 - 10, 21);
  u8g2.drawCircle(W / 2, H / 2, 6);
  u8g2.drawTriangle(W / 2, 3, W / 2 - 4, 8, W / 2 + 4, 8);
  u8g2.setFont(u8g2_font_6x10_tr);
  centered("TOP", W / 2, 19);
  u8g2.drawStr(18, H / 2 + 4, "L");
  u8g2.drawStr(W - 24, H / 2 + 4, "R");
  u8g2.setFont(u8g2_font_5x8_tr);
  centered(FLIP_NAMES[flip], W / 2, H - 8);
}

void drawTextSizes() {
  u8g2.setFont(u8g2_font_4x6_tr);   u8g2.drawStr(0, 6,  "A 4x6  I need some water");
  u8g2.setFont(u8g2_font_5x8_tr);   u8g2.drawStr(0, 16, "B 5x8  I need some water");
  u8g2.setFont(u8g2_font_6x10_tr);  u8g2.drawStr(0, 28, "C 6x10 I need water");
  u8g2.setFont(u8g2_font_7x13_tr);  u8g2.drawStr(0, 43, "D 7x13 need water");
  u8g2.setFont(u8g2_font_9x15_tr);  u8g2.drawStr(0, 61, "E 9x15 water");
}

// Same geometry as firmware/esp32_hud, with the top slot highlighted.
void drawRing() {
  const int N = 8, CX = 64, CY = 32, ORX = 63, ORY = 31, IRX = 30, IRY = 14;
  const int MRX = (ORX + IRX) / 2, MRY = (ORY + IRY) / 2, STEPS = 8;
  const float SEG = 2 * PI / N;
  const char* labels[N] = {"Food", "Warm", "Cool", "Move", "Back", "Light", "Spell", "More"};
  u8g2.drawEllipse(CX, CY, ORX, ORY, U8G2_DRAW_ALL);
  u8g2.drawEllipse(CX, CY, IRX, IRY, U8G2_DRAW_ALL);
  float a0 = -PI / 2 - SEG / 2, da = SEG / STEPS;
  for (int i = 0; i < STEPS; i++) {
    float a = a0 + i * da, b = a + da;
    int ox1 = lround(CX + ORX * cos(a)), oy1 = lround(CY + ORY * sin(a));
    int ox2 = lround(CX + ORX * cos(b)), oy2 = lround(CY + ORY * sin(b));
    int ix1 = lround(CX + IRX * cos(a)), iy1 = lround(CY + IRY * sin(a));
    int ix2 = lround(CX + IRX * cos(b)), iy2 = lround(CY + IRY * sin(b));
    u8g2.drawTriangle(ox1, oy1, ox2, oy2, ix1, iy1);
    u8g2.drawTriangle(ix1, iy1, ox2, oy2, ix2, iy2);
  }
  u8g2.setFont(u8g2_font_5x8_tr);
  u8g2.setFontMode(1);
  for (int k = 0; k < N; k++) {
    float a = -PI / 2 + k * SEG;
    u8g2.setDrawColor(k == 0 ? 0 : 1);
    centered(labels[k], lround(CX + (MRX - 2) * cos(a)), lround(CY + (MRY - 1) * sin(a)) + u8g2.getAscent() / 2);
  }
  u8g2.setDrawColor(1);
  u8g2.setFont(u8g2_font_7x13B_tr);
  centered(labels[0], CX, CY + 5 + u8g2.getAscent() / 2);
}

void drawGrid() {
  for (int x = 0; x < W; x += 16) u8g2.drawVLine(x, 0, H);
  for (int y = 0; y < H; y += 16) u8g2.drawHLine(0, y, W);
  u8g2.drawVLine(W - 1, 0, H);
  u8g2.drawHLine(0, H - 1, W);
  for (int x = 8; x < W; x += 16)
    for (int y = 8; y < H; y += 16) u8g2.drawPixel(x, y);
}

void drawChecker() {
  const int S = 4;
  for (int x = 0; x < W; x += S)
    for (int y = 0; y < H; y += S)
      if (((x / S) + (y / S)) % 2 == 0) u8g2.drawBox(x, y, S, S);
}

void drawWhite() {
  u8g2.drawBox(0, 0, W, H);
  u8g2.setDrawColor(0);
  u8g2.setFont(u8g2_font_6x10_tr);
  centered("ALL PIXELS ON", W / 2, H / 2 + 4);
  u8g2.setDrawColor(1);
}

void drawBigWord() {
  u8g2.setFont(u8g2_font_ncenB14_tr);
  centered("Hello", W / 2, 30);
  u8g2.setFont(u8g2_font_5x8_tr);
  centered("I need some water.", W / 2, 50);
}

void draw() {
  u8g2.clearBuffer();
  u8g2.setDrawColor(1);
  u8g2.setFontMode(0);
  switch (page) {
    case 0: drawAlign(); break;
    case 1: drawTextSizes(); break;
    case 2: drawRing(); break;
    case 3: drawGrid(); break;
    case 4: drawChecker(); break;
    case 5: drawWhite(); break;
    default: drawBigWord(); break;
  }
  if (inverted) {                                   // XOR the whole frame
    u8g2.setDrawColor(2);
    u8g2.drawBox(0, 0, W, H);
    u8g2.setDrawColor(1);
  }
  u8g2.sendBuffer();
}

// ---------- Controls ----------
void report() {
  Serial.printf("screen %d (%s) | flip: %s | brightness: %s | %s%s\n", page, PAGE_NAMES[page], FLIP_NAMES[flip],
                LEVEL_NAMES[level], inverted ? "inverted" : "normal", autoCycle ? " | auto" : "");
}

void showPage(int next) {
  page = (next % PAGES + PAGES) % PAGES;
  lastChange = millis();
  dirty = true;
}

void handleKey(char key) {
  if (key == 'n') showPage(page + 1);
  else if (key == 'p') showPage(page - 1);
  else if (key >= '0' && key < '0' + PAGES) showPage(key - '0');
  else if (key == 'f') { flip = (flip + 1) % FLIPS; u8g2.setDisplayRotation(FLIP_MODES[flip]); dirty = true; }
  else if (key == 'b') { level = (level + 1) % LEVELS; u8g2.setContrast(LEVEL_VALUES[level]); dirty = true; }
  else if (key == 'i') { inverted = !inverted; dirty = true; }
  else if (key == 'a') { autoCycle = !autoCycle; lastChange = millis(); dirty = true; }
}

void readButton() {
  bool btn = digitalRead(BOOT_BTN);
  if (btn == LOW && lastBtn == HIGH && millis() - lastPress > 250) {
    lastPress = millis();
    showPage(page + 1);
  }
  lastBtn = btn;
}

void setup() {
  Serial.begin(115200);
  pinMode(BOOT_BTN, INPUT_PULLUP);
  u8g2.setBusClock(400000);
  u8g2.begin();
  u8g2.setContrast(LEVEL_VALUES[level]);
  Serial.println("OLED test. n/p next/previous, 0-6 jump, f flip, b brightness, i invert, a auto. BOOT button = next.");
}

void loop() {
  while (Serial.available()) handleKey((char)Serial.read());
  readButton();
  if (autoCycle && millis() - lastChange > AUTO_MS) showPage(page + 1);
  if (dirty) {
    dirty = false;
    draw();
    report();
  }
  delay(10);
}
