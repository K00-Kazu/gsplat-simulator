#pragma once

#include <QImage>
#include <QLabel>
#include <QMainWindow>
#include <QString>

class RenderWorker;
class QResizeEvent;

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    explicit MainWindow(QWidget* parent = nullptr);

private:
    void adjustCameraOffset(double deltaX, double deltaZ);
    void applyRenderStatus(const QString& summary, const QString& detail, bool isError);
    void applyPreviewFrame(const QImage& image);
    void refreshPreviewPixmap();
    void refreshCameraOffsetLabel();

    void resizeEvent(QResizeEvent* event) override;

    RenderWorker* render_worker_ = nullptr;
    QLabel* render_status_label_ = nullptr;
    QLabel* render_detail_label_ = nullptr;
    QLabel* camera_offset_label_ = nullptr;
    QLabel* preview_label_ = nullptr;
    QImage latest_preview_image_;
    double camera_offset_x_ = 0.0;
    double camera_offset_z_ = 0.0;
};
