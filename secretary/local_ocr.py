"""On-device OCR only. No model endpoint, cloud request or automatic download."""
import io,json,shutil,subprocess,sys,tempfile
from pathlib import Path

WINDOWS_SCRIPT=r'''
param([string]$ImagePath)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] > $null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime] > $null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] > $null
$asTask=([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {$_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'})[0]
function Await($operation,$type){$task=$asTask.MakeGenericMethod($type).Invoke($null,@($operation));$task.Wait();return $task.Result}
$file=Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream=Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try{
 $decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
 $bitmap=Await ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,[Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied)) ([Windows.Graphics.Imaging.SoftwareBitmap])
 $engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
 if($null -eq $engine){throw 'No installed OCR recognition language'}
 $result=Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
 [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
 @{text=$result.Text}|ConvertTo-Json -Compress
}finally{$stream.Dispose()}
'''

def capability():
    if sys.platform=='darwin':
        import importlib.util
        return {'available':importlib.util.find_spec('Vision') is not None,'engine':'Apple Vision'}
    if sys.platform=='win32':return {'available':True,'engine':'Windows OCR'}
    return {'available':bool(shutil.which('tesseract')),'engine':'Tesseract','message':'本机 OCR 需要安装 Tesseract 和识别语言包。'}

def recognize(image):
    if sys.platform=='darwin':
        import Vision
        from Foundation import NSData
        output=io.BytesIO();image.save(output,'PNG');data=NSData.dataWithBytes_length_(output.getvalue(),output.tell())
        request=Vision.VNRecognizeTextRequest.alloc().init();request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(['zh-Hans','en-US']);request.setUsesLanguageCorrection_(True)
        handler=Vision.VNImageRequestHandler.alloc().initWithData_options_(data,None)
        ok,error=handler.performRequests_error_([request],None)
        if not ok:raise ValueError('本机 OCR 失败：'+str(error))
        return '\n'.join(str(result.topCandidates_(1)[0].string()) for result in request.results() or [])[:8000]
    with tempfile.TemporaryDirectory(prefix='stellar-ocr-') as temp:
        source=Path(temp)/'page.png';image.save(source,'PNG')
        if sys.platform=='win32':
            from .update_transaction import clean_env
            script=Path(temp)/'ocr.ps1';script.write_text(WINDOWS_SCRIPT,encoding='utf-8-sig')
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),str(source)],capture_output=True,timeout=45,env=clean_env(),creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:raise ValueError('Windows 本机 OCR 不可用，请检查已安装的识别语言。')
            return str(json.loads(result.stdout.decode('utf-8-sig'))['text'])[:8000]
        tool=shutil.which('tesseract')
        if not tool:raise ValueError('本机 OCR 需要安装 Tesseract 和识别语言包。')
        from .system_integration import external_env
        env=external_env()
        languages=subprocess.run([tool,'--list-langs'],env=env,capture_output=True,text=True,timeout=10).stdout.splitlines()
        selected='+'.join(value for value in ('chi_sim','eng') if value in languages)
        if not selected:raise ValueError('本机 OCR 缺少中文或英文识别语言包。')
        result=subprocess.run([tool,str(source),'stdout','-l',selected],env=env,capture_output=True,timeout=45)
        if result.returncode:raise ValueError('本机 OCR 无法读取此页面。')
        return result.stdout.decode('utf-8',errors='replace')[:8000]
