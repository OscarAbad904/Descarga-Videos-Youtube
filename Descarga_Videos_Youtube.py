import os
import re
import subprocess
import yt_dlp as youtube_dl
from moviepy.editor import VideoFileClip
from pathlib import Path

from PyQt6 import QtWidgets, uic
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from PyQt6.QtCore import QThreadPool, QRunnable, pyqtSignal, QObject

# -----------------------------------------------------------------------------
# --------------------------- FUNCIÓN DE SANEAMIENTO ---------------------------
# -----------------------------------------------------------------------------

def sanitize_filename(filename: str) -> str:
    """
    Reemplaza caracteres que suelen dar problemas en Windows o en ffmpeg
    (p.ej. <, >, :, ", /, \, |, ?, *). También quita espacios sobrantes al principio/fin.
    """
    # Reemplaza los caracteres conflictivos por '_'
    # Nota: si quieres preservar acentos y eñes, no los toques aquí.
    # Principalmente importa quitar los símbolos que Windows/FFmpeg no toleran.
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Elimina espacios al inicio o final
    filename = filename.strip()
    return filename

# -----------------------------------------------------------------------------
# --------------------------- LÓGICA ADICIONAL --------------------------------
# -----------------------------------------------------------------------------

def verificar_actualizacion_yt_dlp(parent_window):
    """
    Ejecuta un proceso en modo 'dry-run' para ver si hay una nueva versión de yt-dlp.
    Si la hay, copia el comando de actualización al portapapeles y muestra un mensaje.
    """
    try:
        result = subprocess.run(
            ["pip", "install", "--upgrade", "yt-dlp", "--dry-run"],
            capture_output=True,
            text=True
        )
        # Si aparece "Collecting yt-dlp" o "Downloading", hay una versión nueva
        if "Collecting yt-dlp" in result.stdout or "Downloading" in result.stdout:
            cb = parent_window.clipboard()
            cb.setText("pip install --upgrade yt-dlp")
            QMessageBox.information(
                parent_window,
                "Actualización disponible",
                "Hay una nueva versión de yt_dlp disponible.\n"
                "El comando de actualización se ha copiado al portapapeles."
            )
    except Exception as e:
        print(f"Error al verificar la actualización de yt_dlp: {str(e)}")


def obtener_carpeta_descargas():
    """
    Devuelve la ruta de la carpeta de 'Descargas' según el sistema operativo.
    """
    if os.name == 'nt':  # Windows
        return str(Path.home() / "Downloads")
    else:  # macOS y Linux
        return str(Path.home() / "Descargas")


def limpiar_terminal():
    """
    Limpia la consola según el sistema operativo.
    """
    if os.name == 'nt':  # Windows
        os.system('cls')
    else:  # macOS y Linux
        os.system('clear')


def convertir_a_avi_divx(video_path, output_path):
    """
    Convierte un archivo de vídeo a AVI (DivX) sin romper el path original.
    """
    # Separamos carpeta y nombre de archivo
    carpeta = os.path.dirname(output_path)
    nombre_archivo = os.path.basename(output_path)
    
    # Saneamos SOLO el nombre del archivo
    nombre_archivo = sanitize_filename(nombre_archivo)
    
    # Reconstruimos la ruta final correcta
    final_output_path = os.path.join(carpeta, nombre_archivo)

    # Si ya existe, lo borramos para evitar conflictos
    if os.path.exists(final_output_path):
        os.remove(final_output_path)

    comando = [
        'ffmpeg', '-i', video_path, '-c:v', 'mpeg4', '-vtag', 'DIVX', '-q:v', '2', final_output_path
    ]
    subprocess.run(comando, check=True)


def convertir_audio_a_mp3(audio_path, output_path):
    """
    Convierte un archivo de audio a MP3 sin romper la ruta.
    """
    carpeta = os.path.dirname(output_path)
    nombre_archivo = os.path.basename(output_path)
    nombre_archivo = sanitize_filename(nombre_archivo)
    final_output_path = os.path.join(carpeta, nombre_archivo)

    if os.path.exists(final_output_path):
        os.remove(final_output_path)

    comando = [
        'ffmpeg', '-i', audio_path, '-q:a', '0', '-map', 'a', final_output_path
    ]
    subprocess.run(comando, check=True)


def extraer_audio(video_path):
    """
    Extrae el audio a WAV con MoviePy manteniendo la ruta intacta.
    """
    video_clip = VideoFileClip(video_path)

    # Separamos carpeta y nombre base
    carpeta = os.path.dirname(video_path)
    base_sin_ext = os.path.splitext(os.path.basename(video_path))[0]
    # Saneamos SOLO el nombre base, no la carpeta
    base_sin_ext = sanitize_filename(base_sin_ext)

    audio_filename = base_sin_ext + ".wav"
    audio_path = os.path.join(carpeta, audio_filename)

    print(f"Extrayendo audio a: {audio_path}")
    video_clip.audio.write_audiofile(audio_path)

    if os.path.exists(audio_path):
        print(f"Audio extraído correctamente: {audio_path}")
        return audio_path
    else:
        raise RuntimeError("No se pudo crear el archivo de audio.")

# -----------------------------------------------------------------------------
# --------------------------- CLASE PARA DESCARGA -----------------------------
# -----------------------------------------------------------------------------

class DownloadSignals(QObject):
    """Señales personalizadas para actualizar la interfaz desde un hilo."""
    progress = pyqtSignal(float)        # Para actualizar barra de progreso
    finished = pyqtSignal(str)          # Al finalizar la descarga
    error = pyqtSignal(str)             # Para reportar errores


class DownloadTask(QRunnable):
    """
    Tarea (QRunnable) que se ejecuta en un threadpool para descargar y convertir el video.
    """

    def __init__(self, url, carpeta, separar_audio, formato_video, formato_audio):
        super().__init__()
        self.url = url
        self.carpeta = carpeta
        self.separar_audio = separar_audio
        self.formato_video = formato_video
        self.formato_audio = formato_audio
        self.signals = DownloadSignals()

    def actualizar_progreso(self, d):
        if d['status'] == 'downloading':
            # Parseamos el porcentaje
            porcentaje_str = d.get('_percent_str', '0%').strip()
            # Eliminamos caracteres extra
            porcentaje_str = porcentaje_str.replace('%', '').replace('\x1b[0;94m', '').replace('\x1b[0m', '')
            try:
                porcentaje = float(porcentaje_str)
            except ValueError:
                porcentaje = 0.0
            self.signals.progress.emit(porcentaje)

    def run(self):
        try:
            limpiar_terminal()
            # Opciones para yt_dlp
            ydl_opts = {
                'format': 'best',
                'outtmpl': os.path.join(self.carpeta, '%(title)s.%(ext)s'),
                'progress_hooks': [self.actualizar_progreso],
                'noprogress': True,
                'nocheckcertificate': True,
                'no_color': True,
                'verbose': True,
            }

            # Descarga el video con yt_dlp
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(self.url, download=True)
                original_video_path = ydl.prepare_filename(info_dict)

            # Sanitizamos el título y generamos un nombre de archivo seguro
            video_title = info_dict['title']
            safe_title = sanitize_filename(video_title)

            # Renombramos el archivo descargado a uno “seguro” (por si yt_dlp no lo hizo por sí solo)
            # Obtenemos extensión original (e.g. .mp4) y creamos un path con título saneado
            ext_original = os.path.splitext(original_video_path)[1]  # ej. ".mp4"
            sanitized_video_path = os.path.join(self.carpeta, f"{safe_title}{ext_original}")

            if sanitized_video_path != original_video_path:
                os.rename(original_video_path, sanitized_video_path)

            print(f"Video descargado y renombrado a: {sanitized_video_path}")

            # Ahora preparamos la ruta de salida según el formato de video que quiera el usuario
            video_output_path = os.path.join(
                self.carpeta,
                f"{safe_title}.{self.formato_video.lower()}"
            )

            if self.formato_video.lower().startswith("avi"):
                # AVI (DivX)
                convertir_a_avi_divx(sanitized_video_path, video_output_path)
                # Eliminar el archivo original (por ejemplo, .mp4) si se desea
                if os.path.exists(sanitized_video_path):
                    os.remove(sanitized_video_path)
            else:
                # Si el usuario seleccionó MP4, nos quedamos con el archivo tal cual
                # y actualizamos video_output_path para que sea el mismo
                video_output_path = sanitized_video_path

            # Manejo de audio
            if self.separar_audio:
                # Extraemos primero el WAV
                audio_wav_path = extraer_audio(video_output_path)

                if self.formato_audio == "MP3":
                    # Construimos la ruta de salida para MP3
                    audio_output_path = os.path.join(
                        self.carpeta, f"{safe_title}.mp3"
                    )
                    convertir_audio_a_mp3(audio_wav_path, audio_output_path)

                    # Borramos el WAV si ya no lo queremos
                    if os.path.exists(audio_wav_path):
                        os.remove(audio_wav_path)

                    mensaje_final = (
                        f"Se ha creado el archivo \"{safe_title}\" en "
                        f"formatos {self.formato_video} y {self.formato_audio}"
                    )
                else:
                    # Si el usuario quería WAV, lo dejamos en WAV
                    mensaje_final = (
                        f"Se ha creado el archivo \"{safe_title}\" en "
                        f"formatos {self.formato_video} y WAV"
                    )
            else:
                mensaje_final = (
                    f"Video descargado: \"{safe_title}\" en formato {self.formato_video}\n"
                    f"Carpeta: {self.carpeta}"
                )

            self.signals.finished.emit(mensaje_final)

        except youtube_dl.utils.DownloadError as e:
            error_msg = f"Error al descargar el video: {str(e)}"
            print(error_msg)
            self.signals.error.emit(error_msg)
        except Exception as e:
            error_msg = f"Error inesperado: {str(e)}"
            print(error_msg)
            self.signals.error.emit(error_msg)


# -----------------------------------------------------------------------------
# --------------------------- VENTANA PRINCIPAL --------------------------------
# -----------------------------------------------------------------------------

class DescargadorApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        # Cargamos la interfaz desde el .ui
        directorio_base = os.path.dirname(os.path.abspath(__file__))
        uic.loadUi(os.path.join(directorio_base, "Descarga_Videos_Youtube.ui"), self)

        # Referencia a widgets
        self.urlLineEdit = self.findChild(QtWidgets.QLineEdit, "urlLineEdit")
        self.carpetaLineEdit = self.findChild(QtWidgets.QLineEdit, "carpetaLineEdit")
        self.seleccionarCarpetaButton = self.findChild(QtWidgets.QPushButton, "seleccionarCarpetaButton")
        self.separarAudioCheckBox = self.findChild(QtWidgets.QCheckBox, "separarAudioCheckBox")
        self.audioFormatComboBox = self.findChild(QtWidgets.QComboBox, "audioFormatComboBox")
        self.progressBar = self.findChild(QtWidgets.QProgressBar, "progressBar")
        self.descargarButton = self.findChild(QtWidgets.QPushButton, "descargarButton")
        self.videoFormatComboBox = self.findChild(QtWidgets.QComboBox, "videoFormatComboBox")

        # Inicializar valores por defecto
        self.carpetaLineEdit.setText(obtener_carpeta_descargas())
        self.audioFormatComboBox.addItems(["MP3", "WAV"])
        self.audioFormatComboBox.setCurrentIndex(0)  # MP3 por defecto
        self.videoFormatComboBox.addItems(["AVI (DivX)", "MP4"])
        self.videoFormatComboBox.setCurrentIndex(0)  # AVI (DivX) por defecto

        # Ocultar el combo de formato de audio al iniciar
        self.audioFormatComboBox.setVisible(False)

        # Eventos
        self.seleccionarCarpetaButton.clicked.connect(self.seleccionar_carpeta)
        self.separarAudioCheckBox.stateChanged.connect(self.toggle_audio_combo)
        self.descargarButton.clicked.connect(self.descargar_video)

        # Barra de progreso inicial
        self.progressBar.setValue(0)

        # ThreadPool para manejar descargas
        self.threadpool = QThreadPool()

        # Verificamos actualización de yt_dlp
        verificar_actualizacion_yt_dlp(self)

    def seleccionar_carpeta(self):
        carpeta = QFileDialog.getExistingDirectory(
            self, "Selecciona la carpeta de descarga", os.getcwd()
        )
        if carpeta:
            self.carpetaLineEdit.setText(carpeta)

    def toggle_audio_combo(self):
        """
        Muestra u oculta el combo de formato de audio en función del estado del check.
        """
        checked = self.separarAudioCheckBox.isChecked()
        self.audioFormatComboBox.setVisible(checked)

    def actualizar_progreso(self, valor):
        self.progressBar.setValue(int(valor))

    def descargar_video(self):
        url = self.urlLineEdit.text().strip()
        carpeta = self.carpetaLineEdit.text().strip()
        separar_audio = self.separarAudioCheckBox.isChecked()
        formato_audio = self.audioFormatComboBox.currentText()
        # "MP4" o "AVI (DivX)" -> tomamos la primera parte que define el formato real
        formato_video = self.videoFormatComboBox.currentText().split()[0]  

        if not url:
            QMessageBox.critical(self, "Error", "Por favor, ingresa una URL")
            return

        if not carpeta:
            QMessageBox.critical(self, "Error", "Por favor, selecciona una carpeta de descarga")
            return

        # Deshabilitamos el botón para evitar descargas simultáneas
        self.descargarButton.setEnabled(False)

        # Creamos la tarea
        task = DownloadTask(url, carpeta, separar_audio, formato_video, formato_audio)

        # Conectamos las señales
        task.signals.progress.connect(self.actualizar_progreso)
        task.signals.finished.connect(self.on_descarga_finalizada)
        task.signals.error.connect(self.on_descarga_error)

        # Ejecutamos la tarea en segundo plano
        self.threadpool.start(task)

    def on_descarga_finalizada(self, mensaje):
        self.descargarButton.setEnabled(True)
        self.progressBar.setValue(0)
        QMessageBox.information(self, "Éxito", mensaje)

    def on_descarga_error(self, mensaje_error):
        self.descargarButton.setEnabled(True)
        self.progressBar.setValue(0)
        QMessageBox.critical(self, "Error", mensaje_error)


# -----------------------------------------------------------------------------
# --------------------------- EJECUCIÓN DEL PROGRAMA ---------------------------
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    window = DescargadorApp()
    window.show()
    sys.exit(app.exec())