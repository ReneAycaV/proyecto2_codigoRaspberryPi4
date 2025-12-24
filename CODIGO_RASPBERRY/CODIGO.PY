from flask import Flask, jsonify, request, Response
import grovepi
import time
import threading
import json
import datetime
import os
import cv2

app = Flask(__name__)

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

ULTRA_COMIDA = 4
ULTRA_AGUA = 3
RELAY_AGUA = 8
RELAY_COMIDA = 2

grovepi.pinMode(ULTRA_COMIDA, "INPUT")
grovepi.pinMode(ULTRA_AGUA, "INPUT")
grovepi.pinMode(RELAY_AGUA, "OUTPUT")
grovepi.pinMode(RELAY_COMIDA, "OUTPUT")


CONFIG_DISPENSADOR = {
    "altura_total": 26,
    "niveles": {
        "comida": {
            "lleno": (0, 6),
            "medio": (7, 12),
            "poco": (13, 19),
            "vacio": (20, 26)
        },
        "agua": {
            "lleno": (0, 6),
            "medio": (7, 12),
            "poco": (13, 19),
            "vacio": (20, 26)
        }
    }
}

# ================= ESTADO =================
estado = {
    "comida": {
        "distancia_cm": -1,
        "nivel": "desconocido",
        "porcentaje": 0
    },
    "agua": {
        "distancia_cm": -1,
        "nivel": "desconocido",
        "porcentaje": 0
    }
}

# Para controlar la cámara
camera = None
camera_active = False
CONFIG_FILE = "config.json"

# ================= CÁMARA SIMPLIFICADA =================
def init_camera():
    """Inicializa la cámara"""
    global camera, camera_active
    
    if camera_active and camera is not None:
        return True
    
    # Liberar cámara anterior si existe
    if camera is not None:
        camera.release()
    
    # Intentar conectar a la cámara
    camera = cv2.VideoCapture(0)
    
    if not camera.isOpened():
        # Intentar con índice alternativo
        camera = cv2.VideoCapture(1)
        if not camera.isOpened():
            print(" No se pudo conectar a la cámara")
            camera = None
            camera_active = False
            return False
    
    # Configurar parámetros básicos
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    camera.set(cv2.CAP_PROP_FPS, 15)
    
    camera_active = True
    print(" Cámara inicializada correctamente")
    return True

def release_camera():
    """Libera la cámara"""
    global camera, camera_active
    
    if camera is not None:
        camera.release()
        camera = None
    
    camera_active = False
    print(" Cámara liberada")

# ================= UTILIDADES =================
def cargar_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return {"horarios": []}

def guardar_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def calcular_nivel(distancia_cm, tipo):
    if distancia_cm == -1:
        return "error", 0
    
    config = CONFIG_DISPENSADOR["niveles"][tipo]
    
    if config["lleno"][0] <= distancia_cm <= config["lleno"][1]:
        porcentaje = 100 - ((distancia_cm / config["lleno"][1]) * 30)
        return "lleno", max(80, min(100, porcentaje))
    
    elif config["medio"][0] <= distancia_cm <= config["medio"][1]:
        porcentaje = 70 - (((distancia_cm - 7) / 5) * 20)
        return "medio", max(50, min(79, porcentaje))
    
    elif config["poco"][0] <= distancia_cm <= config["poco"][1]:
        porcentaje = 50 - (((distancia_cm - 13) / 6) * 30)
        return "poco", max(20, min(49, porcentaje))
    
    else:
        return "vacio", max(0, min(19, 100 - (distancia_cm * 3)))

def leer_sensores():
    global estado
    while True:
        try:
            distancia = grovepi.ultrasonicRead(ULTRA_COMIDA)
            nivel, porcentaje = calcular_nivel(distancia, "comida")
            estado["comida"] = {
                "distancia_cm": distancia,
                "nivel": nivel,
                "porcentaje": round(porcentaje, 1)
            }
        except Exception as e:
            print(f"Error sensor comida: {e}")
            estado["comida"]["nivel"] = "error"

        try:
            distancia = grovepi.ultrasonicRead(ULTRA_AGUA)
            nivel, porcentaje = calcular_nivel(distancia, "agua")
            estado["agua"] = {
                "distancia_cm": distancia,
                "nivel": nivel,
                "porcentaje": round(porcentaje, 1)
            }
        except Exception as e:
            print(f"Error sensor agua: {e}")
            estado["agua"]["nivel"] = "error"

        time.sleep(2)

def activar_relay(tipo, segundos):
    if tipo == "agua":
        grovepi.digitalWrite(RELAY_AGUA, 1)
        time.sleep(segundos)
        grovepi.digitalWrite(RELAY_AGUA, 0)

def scheduler():
    while True:
        ahora = datetime.datetime.now()
        hora = ahora.strftime("%H:%M")
        dia = ahora.strftime("%A")

        config = cargar_config()

        for h in config["horarios"]:
            if not h["activo"]:
                continue
            if h["hora"] != hora:
                continue
            if dia not in h["dias"]:
                continue

            activar_relay(h["tipo"], h["tiempo"])

        time.sleep(60)

# ================= ENDPOINTS BÁSICOS =================
@app.route("/")
def index():
    return jsonify({
        "app": "Dispensador IoT",
        "status": "running",
        "endpoints": {
            "/estado": "GET - Estado sensores",
            "/niveles": "GET - Niveles procesados",
            "/dispensar": "POST - Dispensar manual",
            "/horarios": "GET/POST - Horarios",
            "/video": "GET - Stream de video MJPEG",
            "/foto": "GET - Foto en tiempo real (memoria)",
            "/foto-guardar": "POST - Tomar y guardar foto en disco"
        }
    })

@app.route("/estado", methods=["GET"])
def get_estado():
    return jsonify({
        "comida": estado["comida"],
        "agua": estado["agua"],
        "timestamp": datetime.datetime.now().isoformat()
    })

@app.route("/niveles", methods=["GET"])
def get_niveles():
    return jsonify({
        "comida": {
            "nivel": estado["comida"]["nivel"],
            "porcentaje": estado["comida"]["porcentaje"]
        },
        "agua": {
            "nivel": estado["agua"]["nivel"],
            "porcentaje": estado["agua"]["porcentaje"]
        }
    })

@app.route("/dispensar", methods=["POST"])
def dispensar_manual():
    data = request.json
    activar_relay(data["tipo"], data["tiempo"])
    return jsonify({"ok": True})

@app.route("/horarios", methods=["GET"])
def get_horarios():
    return jsonify(cargar_config()["horarios"])

@app.route("/horarios", methods=["POST"])
def add_horario():
    data = request.json
    config = cargar_config()

    config["horarios"].append({
        "hora": data["hora"],
        "dias": data["dias"],
        "tipo": data["tipo"],
        "tiempo": data["tiempo"],
        "activo": True
    })

    guardar_config(config)
    return jsonify({"ok": True})

# ================= ENDPOINTS CÁMARA =================
@app.route("/video")
def video():
    """Stream MJPEG para WebView"""
    # Inicializar cámara si no está activa
    if not camera_active:
        if not init_camera():
            return "No se pudo inicializar la cámara", 500
    
    def generate():
        while camera_active:
            success, frame = camera.read()
            if not success:
                break
            
            # Convertir frame a JPEG
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            
            if ret:
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                      b'Content-Type: image/jpeg\r\n\r\n' + 
                      frame_bytes + b'\r\n')
            
            # Controlar FPS (~15 FPS)
            time.sleep(0.066)
    
    return Response(
        generate(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route("/foto")
def foto():
    """Foto en tiempo real (solo en memoria) - NUEVA VERSIÓN"""
    try:
        # Inicializar cámara si no está activa
        if not camera_active:
            if not init_camera():
                return jsonify({"error": "No se pudo inicializar la cámara"}), 500
        
        success, frame = camera.read()
        if not success:
            return jsonify({"error": "No se pudo capturar frame"}), 500
        
        # Convertir frame a JPG en memoria (NO se guarda en disco)
        ret, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        
        if not ret:
            return jsonify({"error": "Error procesando imagen"}), 500
        
        image_bytes = buffer.tobytes()
        
        return Response(
            image_bytes,
            mimetype="image/jpeg",
            headers={
                "Content-Disposition": "inline; filename=foto.jpg",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
        
    except Exception as e:
        print(f"❌ Error en endpoint /foto: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/foto-guardar", methods=["POST"])
def foto_guardar():
    """Tomar y guardar foto en disco (opcional)"""
    try:
        if not camera_active:
            if not init_camera():
                return jsonify({"error": "No se pudo inicializar la cámara"}), 500
        
        success, frame = camera.read()
        if not success:
            return jsonify({"error": "No se pudo capturar frame"}), 500
        
        # Guardar en disco
        carpeta_destino = "mascotas"
        if not os.path.exists(carpeta_destino):
            os.makedirs(carpeta_destino)

        ahora = datetime.datetime.now()
        nombre_archivo = ahora.strftime("MASCOTA_%Y-%m-%d_%H-%M-%S.jpg")
        ruta_completa = os.path.join(carpeta_destino, nombre_archivo)

        exito = cv2.imwrite(ruta_completa, frame)
        
        if exito:
            return jsonify({
                "success": True,
                "message": "Foto guardada en el servidor",
                "filename": nombre_archivo,
                "path": ruta_completa,
                "timestamp": ahora.isoformat()
            })
        else:
            return jsonify({"error": "No se pudo guardar la foto"}), 500
        
    except Exception as e:
        print(f"❌ Error en endpoint /foto-guardar: {e}")
        return jsonify({"error": str(e)}), 500

# ================= MAIN =================
if __name__ == "__main__":
    # Iniciar sensores en hilos
    threading.Thread(target=leer_sensores, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    
    print("=" * 60)
    print("           DISPENSADOR IoT - FOTO EN MEMORIA")
    print("=" * 60)
    print("\n SENSORES INICIADOS:")
    print(f"  Comida: D{ULTRA_COMIDA}")
    print(f"  Agua: D{ULTRA_AGUA}")
    print(f"  Relay agua: D{RELAY_AGUA}")
    
    print("\n ENDPOINTS CÁMARA:")
    print("  GET   /video           - Stream MJPEG")
    print("  GET   /foto            - Foto en tiempo real (memoria)")
    print("  POST  /foto-guardar    - Tomar y guardar foto en disco")
    
    print("=" * 60)
    print(f"\n Servidor iniciado en: http://0.0.0.0:5000")
    print(" Video en vivo: http://<TU_IP>:5000/video")
    print(" Foto instantánea: http://<TU_IP>:5000/foto")
    print("=" * 60)
    
    try:
        app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
    except KeyboardInterrupt:
        print("\n Cerrando servidor...")
        release_camera()
    finally:
        release_camera()