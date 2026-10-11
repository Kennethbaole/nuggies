// ESP32 DevKit V1 + 1.3" SH1106 OLED: ring HUD driven by text commands.
//
// Commands (one per line over USB Serial, or one per WebSocket text message):
//   W:2|Hello|Thanks|Listen|Stay|Back|Love|More|Spell|I love|you.|
//                                            mirror the website (backend.hud_sync): highlighted
//                                            slot (-1 = none), 8 labels (empty = hidden slot),
//                                            3 centre lines. Sent whole on every change and
//                                            once a second; "No link" shows if it stops for 4 s.
//                                            A first centre line starting with "!" replaces the
//                                            wheel with that text, large (e.g. "!DOUBLE BLINK").
//   O:Food,Warm,Cool,Move,Light,Spell,More   new options (up to 7; Back stays at the bottom)
//   H:3                                      highlight slot 3 (0 = top, clockwise; 4 = Back)
//   T:speaking...                            status message for 1.5 s
//   n / p / s                                next / previous / select (local testing)
// On select it reports "SELECTED:<index>:<label>" over Serial and WebSocket. O/H/n/p/s are the
// standalone wheel used by backend.hud_bridge; a W: frame switches to mirroring the website.
//
// Libraries (Arduino Library Manager): "U8g2" by oliver, and
// "WebSockets" by Markus Sattler (arduinoWebSockets).
// Wi-Fi is not usable yet: nothing in the repo serves this WebSocket. Use USB.
//
// Wiring: OLED SDA -> GPIO 21, SCK/SCL -> GPIO 22, VCC -> 3V3, GND -> GND.
// Power: LiPo -> protection/charger -> 5 V boost -> VIN, never LiPo straight
// to 3V3 or VIN. Do not power from USB and battery at the same time.

#include <U8g2lib.h>
#include <Wire.h>
#include <math.h>

// ---------- Settings ----------
#define USE_WIFI 0          // 1 = join the hotspot and connect to the WebSocket server
#define FLIP_MODE 1         // 0 = normal, 1 = mirror left-right, 2 = mirror top-bottom

// Copy secrets.example.h to secrets.h (ignored by Git) and put the real values there.
#if __has_include("secrets.h")
  #include "secrets.h"
#else
  #define WIFI_SSID "YOUR_HOTSPOT_NAME"
  #define WIFI_PASS "YOUR_HOTSPOT_PASSWORD"
  #define WS_HOST   "10.42.0.1"          // the Jetson on its own hotspot (NetworkManager default)
#endif
#ifndef WS_PORT
  #define WS_PORT 8766                   // placeholder: 8765 is the website (HTTP only, no WebSocket)
#endif
#ifndef WS_PATH
  #define WS_PATH "/"
#endif

#if FLIP_MODE == 1
  #define ROTATION U8G2_MIRROR
#elif FLIP_MODE == 2
  #define ROTATION U8G2_MIRROR_VERTICAL
#else
  #define ROTATION U8G2_R0
#endif

U8G2_SH1106_128X64_NONAME_F_HW_I2C u8g2(ROTATION, U8X8_PIN_NONE);

#if USE_WIFI
  #include <WiFi.h>
  #include <WebSocketsClient.h>
  WebSocketsClient webSocket;
  bool wsConnected = false;
#endif

// ---------- Options ----------
const int N = 8;
const int BACK_INDEX = 4;
const int MAX_LABEL = 10;
char labels[N][MAX_LABEL + 1] = {"Food", "Warm", "Cool", "Move", "Back", "Light", "Spell", "More"};

// ---------- Ring geometry ----------
const int CX = 64, CY = 32;
// RING_PERCENT shrinks the outer ring from the full 128x64 panel (100 = edge to edge).
// The inner ellipse stays fixed: hud_sync wraps the centre text to fit it.
const int RING_PERCENT = 85;
const int ORX = 63 * RING_PERCENT / 100, ORY = 31 * RING_PERCENT / 100, IRX = 30, IRY = 14;
const int MRX = (ORX + IRX) / 2, MRY = (ORY + IRY) / 2;
const float SEG = 2 * PI / N;
const int BOOT_BTN = 0;

// ---------- State ----------
int selected = 0;
float wedge = -PI / 2, wedgeTarget = -PI / 2;
char statusText[24] = "";
unsigned long statusUntil = 0;
unsigned long lastPress = 0;
bool lastBtn = HIGH;
char lineBuf[200];
int lineLen = 0;

// Mirror mode: the website owns the picture and sends it whole in W: frames.
const int CENTER_LINES = 3;
const int MAX_CENTER = 14;
const unsigned long LINK_TIMEOUT_MS = 4000;
bool mirrorMode = false;
bool highlight = true;
char centerText[CENTER_LINES][MAX_CENTER + 1];
unsigned long lastFrame = 0;

float slotAngle(int k) { return -PI / 2 + k * SEG; }
bool slotEmpty(int k) { return labels[k][0] == '\0'; }

void drawCentered(const char* s, int x, int y) {
  int w = u8g2.getStrWidth(s);
  u8g2.drawStr(x - w / 2, y + u8g2.getAscent() / 2, s);
}

// ---------- Selection ----------
void moveTo(int k) {
  int diff = (k - selected + N) % N;
  if (diff > N / 2) diff -= N;          // rotate the short way round
  wedgeTarget += diff * SEG;
  selected = k;
}

void next() {
  int k = selected;
  do { k = (k + 1) % N; } while (slotEmpty(k) && k != selected);
  moveTo(k);
}

void prev() {
  int k = selected;
  do { k = (k - 1 + N) % N; } while (slotEmpty(k) && k != selected);
  moveTo(k);
}

void showStatus(const char* s, unsigned long ms) {
  strncpy(statusText, s, sizeof(statusText) - 1);
  statusText[sizeof(statusText) - 1] = '\0';
  statusUntil = millis() + ms;
}

void report(const char* message) {
  Serial.println(message);
#if USE_WIFI
  if (wsConnected) webSocket.sendTXT(message);
#endif
}

void doSelect() {
  char msg[40];
  snprintf(msg, sizeof(msg), "SELECTED:%d:%s", selected, labels[selected]);
  report(msg);
  showStatus(selected == BACK_INDEX ? "going back..." : "speaking...", 1500);
}

// ---------- Commands ----------
void setOptions(char* list) {
  for (int k = 0; k < N; k++) if (k != BACK_INDEX) labels[k][0] = '\0';
  int slot = 0;
  char* tok = strtok(list, ",");
  while (tok != NULL && slot < N) {
    if (slot == BACK_INDEX) slot++;
    if (slot >= N) break;
    while (*tok == ' ') tok++;
    strncpy(labels[slot], tok, MAX_LABEL);
    labels[slot][MAX_LABEL] = '\0';
    slot++;
    tok = strtok(NULL, ",");
  }
  strcpy(labels[BACK_INDEX], "Back");
  selected = 0;
  wedge = wedgeTarget = -PI / 2;
  if (slotEmpty(0)) next();
}

// W:<selected>|<8 labels>|<3 centre lines>. Fields are split by hand because
// strtok would skip the empty ones that mark hidden slots.
void setFrame(char* frame) {
  const int FIELDS = 1 + N + CENTER_LINES;
  char* field[FIELDS];
  int count = 0;
  field[count++] = frame;
  for (char* c = frame; *c != '\0' && count < FIELDS; c++) {
    if (*c == '|') { *c = '\0'; field[count++] = c + 1; }
  }
  if (count < 1 + N) return;            // not a complete frame; keep the last picture

  for (int k = 0; k < N; k++) {
    strncpy(labels[k], field[1 + k], MAX_LABEL);
    labels[k][MAX_LABEL] = '\0';
  }
  for (int i = 0; i < CENTER_LINES; i++) {
    strncpy(centerText[i], 1 + N + i < count ? field[1 + N + i] : "", MAX_CENTER);
    centerText[i][MAX_CENTER] = '\0';
  }

  int k = atoi(field[0]);
  bool show = k >= 0 && k < N && !slotEmpty(k);
  if (show && mirrorMode && highlight) moveTo(k);          // glide from the previous slot
  else if (show) { selected = k; wedge = wedgeTarget = slotAngle(k); }
  highlight = show;
  mirrorMode = true;
  statusUntil = 0;
  lastFrame = millis();
}

void handleCommand(char* cmd) {
  if (strncmp(cmd, "W:", 2) == 0)      { setFrame(cmd + 2); return; }
  if (mirrorMode) {                    // the website owns the wheel; only status text is local
    if (strncmp(cmd, "T:", 2) == 0) showStatus(cmd + 2, 1500);
    return;
  }
  if (strncmp(cmd, "O:", 2) == 0)      setOptions(cmd + 2);
  else if (strncmp(cmd, "H:", 2) == 0) { int k = atoi(cmd + 2); if (k >= 0 && k < N && !slotEmpty(k)) moveTo(k); }
  else if (strncmp(cmd, "T:", 2) == 0) showStatus(cmd + 2, 1500);
  else if (strcmp(cmd, "n") == 0)      next();
  else if (strcmp(cmd, "p") == 0)      prev();
  else if (strcmp(cmd, "s") == 0)      doSelect();
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      lineBuf[lineLen] = '\0';
      if (lineLen > 0) handleCommand(lineBuf);
      lineLen = 0;
    } else if (lineLen < (int)sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    }
  }
}

void readButton() {
  bool btn = digitalRead(BOOT_BTN);   // BOOT button = next (handy without a laptop)
  if (lastBtn == HIGH && btn == LOW && millis() - lastPress > 200) {
    if (!mirrorMode) next();
    lastPress = millis();
  }
  lastBtn = btn;
}

#if USE_WIFI
void onWebSocket(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      wsConnected = true;
      webSocket.sendTXT("{\"type\":\"hello\",\"role\":\"glasses\"}");
      showStatus("connected", 1000);
      break;
    case WStype_DISCONNECTED:
      wsConnected = false;
      break;
    case WStype_TEXT: {
      char buf[200];
      size_t n = length < sizeof(buf) - 1 ? length : sizeof(buf) - 1;
      memcpy(buf, payload, n);
      buf[n] = '\0';
      handleCommand(buf);
      break;
    }
    default:
      break;
  }
}
#endif

// ---------- Drawing ----------
void fillWedge(float c) {
  const int STEPS = 8;
  float a0 = c - SEG / 2, da = SEG / STEPS;
  for (int i = 0; i < STEPS; i++) {
    float a = a0 + i * da, b = a + da;
    int ox1 = lround(CX + ORX * cos(a)), oy1 = lround(CY + ORY * sin(a));
    int ox2 = lround(CX + ORX * cos(b)), oy2 = lround(CY + ORY * sin(b));
    int ix1 = lround(CX + IRX * cos(a)), iy1 = lround(CY + IRY * sin(a));
    int ix2 = lround(CX + IRX * cos(b)), iy2 = lround(CY + IRY * sin(b));
    u8g2.drawTriangle(ox1, oy1, ox2, oy2, ix1, iy1);
    u8g2.drawTriangle(ix1, iy1, ox2, oy2, ix2, iy2);
  }
}

void drawPulse(int x, int y) {
  u8g2.drawLine(x - 8, y, x - 3, y);
  u8g2.drawLine(x - 3, y, x - 1, y - 5);
  u8g2.drawLine(x - 1, y - 5, x + 2, y + 4);
  u8g2.drawLine(x + 2, y + 4, x + 4, y);
  u8g2.drawLine(x + 4, y, x + 8, y);
}

void drawStatus() {
  u8g2.setDrawColor(1);
  if (mirrorMode) {                     // the highlighted slot may be hidden or absent
    u8g2.setFont(u8g2_font_7x13B_tr);
    drawCentered(statusText, 64, 32);
    return;
  }
  u8g2.setFont(u8g2_font_ncenB14_tr);
  drawCentered(labels[selected], 64, 26);
  u8g2.setFont(u8g2_font_5x8_tr);
  drawCentered(statusText, 64, 52);
}

// Centre text from the website, already wrapped by hud_sync to fit the inner ellipse.
void drawCenterText() {
  int count = 0;
  for (int i = 0; i < CENTER_LINES; i++) if (centerText[i][0] != '\0') count++;
  u8g2.setFont(u8g2_font_4x6_tr);
  int row = 0;
  for (int i = 0; i < CENTER_LINES; i++) {
    if (centerText[i][0] == '\0') continue;
    drawCentered(centerText[i], CX, CY + lround((row - (count - 1) / 2.0f) * 7));
    row++;
  }
}

// Full-screen cue from the website, e.g. the moment a double blink will be accepted.
void drawAlert() {
  u8g2.setDrawColor(1);
  for (int i = 0; i < 3; i++) u8g2.drawFrame(i, i, 128 - 2 * i, 64 - 2 * i);
  u8g2.setFont(u8g2_font_9x15B_tr);
  drawCentered(centerText[0] + 1, CX, 24);
  u8g2.setFont(u8g2_font_7x13_tr);
  drawCentered(centerText[1], CX, 46);
}

void drawRing() {
  u8g2.setDrawColor(1);
  u8g2.drawEllipse(CX, CY, ORX, ORY, U8G2_DRAW_ALL);
  u8g2.drawEllipse(CX, CY, IRX, IRY, U8G2_DRAW_ALL);
  if (highlight) fillWedge(wedge);

  u8g2.setFont(u8g2_font_5x8_tr);
  u8g2.setFontMode(1);
  for (int k = 0; k < N; k++) {
    if (slotEmpty(k)) continue;
    float a = slotAngle(k);
    u8g2.setDrawColor(highlight && k == selected ? 0 : 1);
    drawCentered(labels[k], lround(CX + (MRX - 2) * cos(a)), lround(CY + (MRY - 1) * sin(a)));
  }

  u8g2.setDrawColor(1);
  if (mirrorMode) {
    drawCenterText();
  } else {
    drawPulse(CX, CY - 6);
    u8g2.setFont(u8g2_font_7x13B_tr);
    drawCentered(labels[selected], CX, CY + 5);
  }

#if USE_WIFI
  if (!wsConnected) u8g2.drawDisc(124, 3, 2);   // small dot = not connected to the server
#endif
}

void setup() {
  Serial.begin(115200);
  pinMode(BOOT_BTN, INPUT_PULLUP);
  u8g2.setBusClock(400000);
  u8g2.begin();
#if USE_WIFI
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  webSocket.begin(WS_HOST, WS_PORT, WS_PATH);
  webSocket.onEvent(onWebSocket);
  webSocket.setReconnectInterval(2000);   // keeps retrying if the server restarts
#endif
  Serial.println("Ready. Try: O:Food,Warm,Cool,Move,Light,Spell,More");
}

void loop() {
  readSerial();
  readButton();
#if USE_WIFI
  webSocket.loop();
#endif
  if (mirrorMode && millis() - lastFrame > LINK_TIMEOUT_MS) {   // backend.hud_sync stopped or the link dropped
    for (int k = 0; k < N; k++) labels[k][0] = '\0';
    strcpy(centerText[0], "No link");
    centerText[1][0] = centerText[2][0] = '\0';
    highlight = false;
    lastFrame = millis();
  }

  wedge += (wedgeTarget - wedge) * 0.3f;
  if (fabs(wedgeTarget - wedge) < 0.001) {
    while (wedgeTarget > 2 * PI)  { wedgeTarget -= 2 * PI; wedge -= 2 * PI; }
    while (wedgeTarget < -2 * PI) { wedgeTarget += 2 * PI; wedge += 2 * PI; }
  }

  u8g2.clearBuffer();
  if (millis() < statusUntil) drawStatus();
  else if (mirrorMode && centerText[0][0] == '!') drawAlert();
  else drawRing();
  u8g2.sendBuffer();
  delay(20);
}
