namespace ALAuto.Util
{
    public class Region
    {
        public int X { get; set; }
        public int Y { get; set; }
        public int Width { get; set; }
        public int Height { get; set; }

        public Region(int x, int y, int width, int height)
        {
            X = x;
            Y = y;
            Width = width;
            Height = height;
        }

        public bool EqualApproximated(Region other, int tolerance = 15)
        {
            int validXMin = X - tolerance;
            int validXMax = X + tolerance;
            int validYMin = Y - tolerance;
            int validYMax = Y + tolerance;
            int validWMin = Width - tolerance;
            int validWMax = Width + tolerance;
            int validHMin = Height - tolerance;
            int validHMax = Height + tolerance;

            return (validXMin <= other.X && other.X <= validXMax &&
                    validYMin <= other.Y && other.Y <= validYMax &&
                    validWMin <= other.Width && other.Width <= validWMax &&
                    validHMin <= other.Height && other.Height <= validHMax);
        }

        public Region Intersection(Region other)
        {
            int x1 = Math.Max(X, other.X);
            int y1 = Math.Max(Y, other.Y);
            int x2 = Math.Min(X + Width, other.X + other.Width);
            int y2 = Math.Min(Y + Height, other.Y + other.Height);

            if (x1 < x2 && y1 < y2)
            {
                return new Region(x1, y1, x2 - x1, y2 - y1);
            }
            return null;
        }

        public int[] GetCenter()
        {
            return new int[] { (X * 2 + Width) / 2, (Y * 2 + Height) / 2 };
        }

        public bool Contains(int[] coords)
        {
            return (X <= coords[0] && coords[0] <= (X + Width)) && (Y <= coords[1] && coords[1] <= (Y + Height));
        }
    }
}
