import os
import subprocess
import threading
import yt_dlp as youtube_dl
from moviepy.editor import VideoFileClip
from pathlib import Path

from PyQt6 import QtWidgets, uic
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from PyQt6.QtCore import QThreadPool, QRunnable, pyqtSignal, QObject

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
            # Copiamos el comando al portapapeles
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
    # Eliminar el archivo de salida si ya existe
    if os.path.exists(output_path):
        os.remove(output_path)
    
    comando = [
        'ffmpeg', '-i', video_path, '-c:v', 'mpeg4', '-vtag', 'DIVX', '-q:v', '2', output_path
    ]
    subprocess.run(comando, check=True)


def convertir_audio_a_mp3(audio_path, output_path):
    # Eliminar el archivo de salida si ya existe
    if os.path.exists(output_path):
        os.remove(output_path)
            
    comando = [
        'ffmpeg', '-i', audio_path, '-q:a', '0', '-map', 'a', output_path
    ]
    subprocess.run(comando, check=True)


def extraer_audio(video_path):
    """
    Extrae el audio en formato WAV usando moviepy.
    Devuelve la ruta al archivo .wav generado.
    """
    video_clip = VideoFileClip(video_path)
    audio_path = os.path.splitext(video_path)[0] + ".wav"
    print(f"Extrayendo audio a: {audio_path}")
    video_clip.audio.write_audiofile(audio_path)

    if os.path.exists(audio_path):
        print(f"Audio extraído correctamente.\nArchivo: {audio_path}")
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

            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(self.url, download=True)
                video_path = ydl.prepare_filename(info_dict)
                print(f"Video descargado en: {video_path}")

            # Convertir video si es necesario
            video_output_path = os.path.join(
                self.carpeta, f"{info_dict['title']}.{self.formato_video.lower()}"
            )

            if self.formato_video.lower().startswith("avi"):
                # AVI (DivX)
                convertir_a_avi_divx(video_path, video_output_path)
                # Eliminar el archivo MP4 original
                if os.path.exists(video_path):
                    os.remove(video_path)
            else:
                video_output_path = video_path  # No se requiere conversión (MP4)

            # Manejo de audio
            if self.separar_audio:
                # Extraemos el WAV primero
                audio_wav_path = extraer_audio(video_output_path)
                # Si el usuario quiere MP3, convertimos
                if self.formato_audio == "MP3":
                    audio_output_path = os.path.join(
                        self.carpeta, f"{info_dict['title']}.mp3"
                    )
                    convertir_audio_a_mp3(audio_wav_path, audio_output_path)
                    # Eliminar el archivo WAV original
                    if os.path.exists(audio_wav_path):
                        os.remove(audio_wav_path)
                    mensaje_final = (
                        f"Se ha creado el archivo \"{info_dict['title']}\" en "
                        f"formatos {self.formato_video} y {self.formato_audio}"
                    )
                else:
                    # Si es WAV, se queda en WAV
                    mensaje_final = (
                        f"Se ha creado el archivo \"{info_dict['title']}\" en "
                        f"formatos {self.formato_video} y WAV"
                    )
            else:
                mensaje_final = (
                    f"Video descargado: \"{info_dict['title']}\" en formato {self.formato_video}\n"
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
        formato_video = self.videoFormatComboBox.currentText().split()[0]  # "MP4" o "AVI"

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