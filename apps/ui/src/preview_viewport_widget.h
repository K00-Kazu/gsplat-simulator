#pragma once

#include "render_worker.h"

#include <QImage>
#include <QRectF>
#include <QWidget>

class QPaintEvent;
class QPainter;

class PreviewViewportWidget : public QWidget
{
public:
    explicit PreviewViewportWidget(QWidget* parent = nullptr);

    void setPreviewFrame(const QImage& image, qint64 frameId);
    void setPreviewCameraState(const PreviewCameraState& state);

protected:
    void paintEvent(QPaintEvent* event) override;

private:
    QRectF buildImageRect() const;
    void paintEmptyState(QPainter& painter, const QRectF& viewportRect) const;
    void paintFrame(QPainter& painter, const QRectF& imageRect) const;
    void paintOverlay(QPainter& painter, const QRectF& imageRect) const;
    void paintPreviewBadge(QPainter& painter, const QRectF& imageRect) const;
    void paintGizmo(QPainter& painter, const QRectF& imageRect) const;

    QImage latestFrame_;
    qint64 latestFrameId_ = -1;
    PreviewCameraState latestCameraState_;
    bool hasCameraState_ = false;
};
