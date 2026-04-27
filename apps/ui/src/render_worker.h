#pragma once

#include <QImage>
#include <QObject>
#include <QString>
#include <QVector3D>

#include <memory>
#include <optional>
#include <vector>

struct PreviewCameraState
{
    qint64 frameId = -1;
    QString timestamp;
    QString cameraRole;
    QVector3D eye;
    QVector3D target;
    QVector3D up = QVector3D(0.0f, 0.0f, 1.0f);
    QVector3D sceneCenter;
    float sceneRadius = 0.0f;
    float focalLengthPx = 0.0f;
    int imageWidth = 0;
    int imageHeight = 0;
    QString worldUpAxis;
    bool gizmoEnabled = false;
};

Q_DECLARE_METATYPE(PreviewCameraState)

struct PreviewSettingsState
{
    QString plyPath;
    float focalLengthPx = 0.0f;
};

Q_DECLARE_METATYPE(PreviewSettingsState)

class RenderWorker : public QObject
{
    Q_OBJECT

public:
    struct FrameMetadata
    {
        qint64 frameId = -1;
        QString timestamp;
        int width = 0;
        int height = 0;
        int stride = 0;
        QString pixelFormat;
    };

    explicit RenderWorker(QObject* parent = nullptr);
    ~RenderWorker() override;

    void subscribe();
    void requestPreviewSettingsUpdate(float focalLengthPx, const QString& plyPath);
    void requestPreviewRenderCommand(
        float panX,
        float panY,
        float panZ,
        float yawDegrees,
        float pitchDegrees,
        float focalLengthPx,
        const QString& plyPath);
    void requestPreviewCameraControl(float panX, float panY, float panZ, float yawDegrees, float pitchDegrees);
    void requestCameraOffset(float offsetX, float offsetY, float offsetZ);

signals:
    void statusChanged(const QString& summary, const QString& detail, bool isError);
    void frameReady(const QImage& image, qint64 frameId);
    void previewCameraStateChanged(const PreviewCameraState& state);
    void previewSettingsChanged(const PreviewSettingsState& state);

private:
    void emitStatus(const QString& summary, const QString& detail, bool isError);
    void storeFrameMetadata(const FrameMetadata& metadata);
    void storePendingFramePayload(const std::vector<uint8_t>& payload);
    void processFramePayload(const std::vector<uint8_t>& payload);
    std::optional<FrameMetadata> latestFrameMetadata() const;
    std::optional<std::vector<uint8_t>> takePendingFramePayload();

#if GSPLAT_UI_WITH_ZENOH
    class Impl;
    std::unique_ptr<Impl> impl_;
#endif
};
