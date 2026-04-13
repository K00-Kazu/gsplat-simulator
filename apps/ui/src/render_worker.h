#pragma once

#include <QImage>
#include <QObject>
#include <QString>

#include <memory>
#include <optional>

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
    void requestCameraOffset(float offsetX, float offsetY, float offsetZ);

signals:
    void statusChanged(const QString& summary, const QString& detail, bool isError);
    void frameReady(const QImage& image);

private:
    void emitStatus(const QString& summary, const QString& detail, bool isError);
    void storeFrameMetadata(const FrameMetadata& metadata);
    std::optional<FrameMetadata> latestFrameMetadata() const;

#if GSPLAT_UI_WITH_ZENOH
    class Impl;
    std::unique_ptr<Impl> impl_;
#endif
};
