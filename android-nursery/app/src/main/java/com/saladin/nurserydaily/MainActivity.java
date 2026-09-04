package com.saladin.nurserydaily;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

public class MainActivity extends Activity {
    private static final int REQ_SAVE = 4101;
    private static final int REQ_FILE = 4102;

    private WebView webView;
    private ValueCallback<Uri[]> filePathCallback;
    private String pendingFileName;
    private String pendingMime;
    private byte[] pendingBytes;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        webView = new WebView(this);
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setTextZoom(100);

        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             FileChooserParams fileChooserParams) {
                if (filePathCallback != null) {
                    filePathCallback.onReceiveValue(null);
                }
                filePathCallback = callback;
                Intent intent;
                try {
                    intent = fileChooserParams.createIntent();
                } catch (Exception ex) {
                    filePathCallback = null;
                    Toast.makeText(MainActivity.this, "امکان باز کردن فایل‌منیجر نیست", Toast.LENGTH_LONG).show();
                    return false;
                }
                try {
                    startActivityForResult(intent, REQ_FILE);
                    return true;
                } catch (Exception ex) {
                    filePathCallback = null;
                    Toast.makeText(MainActivity.this, "فایل‌منیجر پیدا نشد", Toast.LENGTH_LONG).show();
                    return false;
                }
            }
        });

        webView.addJavascriptInterface(new AndroidBridge(), "AndroidBridge");
        webView.loadUrl("file:///android_asset/index.html");
    }

    public final class AndroidBridge {
        @JavascriptInterface
        public void saveFile(String name, String text, String mime) {
            byte[] bytes = (text == null ? "" : text).getBytes(StandardCharsets.UTF_8);
            queueSave(name, mime, bytes);
        }

        @JavascriptInterface
        public void saveBase64File(String name, String base64, String mime) {
            try {
                byte[] bytes = Base64.decode(base64 == null ? "" : base64, Base64.DEFAULT);
                queueSave(name, mime, bytes);
            } catch (Exception ex) {
                runOnUiThread(() -> Toast.makeText(MainActivity.this, "خطا در آماده‌سازی فایل", Toast.LENGTH_LONG).show());
            }
        }
    }

    private void queueSave(String name, String mime, byte[] bytes) {
        pendingFileName = sanitizeName(name);
        pendingBytes = bytes == null ? new byte[0] : bytes;
        pendingMime = (mime == null || mime.trim().isEmpty()) ? "application/octet-stream" : mime;
        runOnUiThread(() -> {
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType(pendingMime);
            intent.putExtra(Intent.EXTRA_TITLE, pendingFileName);
            try {
                startActivityForResult(intent, REQ_SAVE);
            } catch (Exception ex) {
                Toast.makeText(MainActivity.this, "امکان ذخیره فایل نیست", Toast.LENGTH_LONG).show();
            }
        });
    }

    private String sanitizeName(String name) {
        String value = (name == null || name.trim().isEmpty()) ? "nursery_export.bin" : name.trim();
        return value.replace('/', '_').replace('\\', '_');
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);

        if (requestCode == REQ_FILE) {
            if (filePathCallback != null) {
                Uri[] results = null;
                if (resultCode == RESULT_OK && data != null) {
                    Uri uri = data.getData();
                    if (uri != null) results = new Uri[]{uri};
                }
                filePathCallback.onReceiveValue(results);
                filePathCallback = null;
            }
            return;
        }

        if (requestCode == REQ_SAVE) {
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                Uri uri = data.getData();
                try (OutputStream out = getContentResolver().openOutputStream(uri, "w")) {
                    if (out == null) throw new IllegalStateException("output stream is null");
                    out.write(pendingBytes == null ? new byte[0] : pendingBytes);
                    out.flush();
                    Toast.makeText(this, "فایل ذخیره شد", Toast.LENGTH_SHORT).show();
                } catch (Exception ex) {
                    Toast.makeText(this, "خطا در ذخیره فایل", Toast.LENGTH_LONG).show();
                }
            }
            pendingFileName = null;
            pendingMime = null;
            pendingBytes = null;
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }
}
