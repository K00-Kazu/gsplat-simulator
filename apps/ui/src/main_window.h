#pragma once

#include <QLabel>
#include <QMainWindow>

class MainWindow : public QMainWindow
{
public:
    explicit MainWindow(QWidget* parent = nullptr);

private:
    void applyZenohSmokeTestResult();

    QLabel* zenoh_status_label_ = nullptr;
    QLabel* zenoh_detail_label_ = nullptr;
};
