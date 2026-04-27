#pragma once

#include <QImage>
#include <QLabel>
#include <QMainWindow>
#include <QString>

struct PreviewCameraState;
struct PreviewSettingsState;
class RenderWorker;
class PreviewViewportWidget;
class QResizeEvent;

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    explicit MainWindow(QWidget* parent = nullptr, bool autoSubscribe = true);

private:
    void adjustCameraZoom(double scaleFactor);
    void adjustCameraPan(double deltaX, double deltaZ);
    void adjustCameraOrbit(double deltaYawDegrees, double deltaPitchDegrees);
    void browsePreviewScenePath();
    void applyRenderStatus(const QString& summary, const QString& detail, bool isError);
    void applyPreviewFrame(const QImage& image, qint64 frameId);
    void applyPreviewCameraState(const PreviewCameraState& state);
    void applyPreviewSettingsState(const PreviewSettingsState& state);
    void refreshRenderDetailLabel();
    void refreshCameraControlLabels();
    void sendPreviewCameraControl();

    void resizeEvent(QResizeEvent* event) override;

    RenderWorker* render_worker_ = nullptr;
    QLabel* render_status_label_ = nullptr;
    QLabel* render_detail_label_ = nullptr;
    QLabel* camera_zoom_label_ = nullptr;
    QLabel* camera_pan_label_ = nullptr;
    QLabel* camera_rotation_label_ = nullptr;
    QLabel* current_scene_label_ = nullptr;
    PreviewViewportWidget* preview_viewport_ = nullptr;
    QString render_detail_text_;
    QString scene_ply_path_;
    double camera_focal_length_px_ = 900.0;
    double camera_pan_x_ = 0.0;
    double camera_pan_z_ = 0.0;
    double camera_yaw_degrees_ = 0.0;
    double camera_pitch_degrees_ = 0.0;
};
